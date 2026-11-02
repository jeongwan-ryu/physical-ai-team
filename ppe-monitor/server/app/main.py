import hmac
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

DEVICE_KEY = os.environ["DEVICE_KEY"]
DB_PATH = "/data/ppe.db"
MEDIA_DIR = "/data/media"
MAX_IMAGE_BYTES = 1024 * 1024
ONLINE_WINDOW_S = 15


class Person(BaseModel):
    bbox: list[int]
    conf: float
    helmet: bool
    vest: bool


class Meta(BaseModel):
    device_id: str
    ts: str
    trigger: Literal["interval", "violation"]
    frame_w: int
    frame_h: int
    persons: list[Person]


def db():
    # 요청마다 새로 연결 (스레드 문제 회피)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


os.makedirs(MEDIA_DIR, exist_ok=True)
con = db()
con.execute(
    "CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT, ts TEXT, "
    "trigger TEXT, person_count INT, no_helmet INT, no_vest INT, persons TEXT, image TEXT, received_at REAL)"
)
con.close()

# 최신 프레임 1장: (jpeg bytes, 받은 시각). uvicorn worker 1개 전제
latest_frame = None

app = FastAPI()


def check_key(key):
    if not hmac.compare_digest((key or "").encode(), DEVICE_KEY.encode()):
        raise HTTPException(401, "invalid X-Device-Key")


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@app.post("/api/events", status_code=201)
async def post_event(
    meta: str = Form(),
    image: UploadFile | None = File(None),
    x_device_key: str | None = Header(None),
):
    check_key(x_device_key)
    try:
        m = Meta.model_validate_json(meta)
    except ValidationError as e:
        raise HTTPException(422, f"invalid meta: {e.errors(include_url=False)}")

    data = await image.read() if image else b""
    if m.trigger == "violation" and not data:
        raise HTTPException(422, "violation requires image")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "image larger than 1 MB")

    con = db()
    cur = con.execute(
        "INSERT INTO events(device_id, ts, trigger, person_count, no_helmet, no_vest, persons, image, received_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)",
        (
            m.device_id,
            m.ts,
            m.trigger,
            len(m.persons),
            sum(not p.helmet for p in m.persons),
            sum(not p.vest for p in m.persons),
            json.dumps([p.model_dump() for p in m.persons]),
            time.time(),
        ),
    )
    event_id = cur.lastrowid
    image_url = None
    if data:
        with open(f"{MEDIA_DIR}/{event_id}.jpg", "wb") as f:
            f.write(data)
        image_url = f"/media/{event_id}.jpg"
        con.execute("UPDATE events SET image = ? WHERE id = ?", (image_url, event_id))
    con.commit()
    con.close()
    return {"id": event_id, "image_url": image_url}


@app.put("/api/frame", status_code=204)
async def put_frame(request: Request, x_device_key: str | None = Header(None)):
    global latest_frame
    check_key(x_device_key)
    latest_frame = (await request.body(), time.time())
    return Response(status_code=204)


@app.get("/api/frame")
def get_frame():
    if latest_frame is None:
        raise HTTPException(404, "no frame yet")
    return Response(latest_frame[0], media_type="image/jpeg")


@app.get("/api/latest")
def get_latest():
    con = db()
    row = con.execute("SELECT * FROM events ORDER BY id DESC LIMIT 1").fetchone()
    con.close()

    # online: server 시각 기준으로 최근 15초 안에 이벤트나 프레임을 받았는지
    last_seen = max(row["received_at"] if row else 0, latest_frame[1] if latest_frame else 0)
    result = {
        "online": time.time() - last_seen < ONLINE_WINDOW_S,
        "ts": None,
        "person_count": 0,
        "no_helmet": 0,
        "no_vest": 0,
        "persons": [],
        "frame_ts": iso(latest_frame[1]) if latest_frame else None,
    }
    if row:
        result.update(
            ts=row["ts"],
            person_count=row["person_count"],
            no_helmet=row["no_helmet"],
            no_vest=row["no_vest"],
            persons=json.loads(row["persons"]),
        )
    return result


@app.get("/api/events")
def get_events(only_violations: bool = False, limit: int = 50):
    limit = min(max(limit, 1), 200)
    sql = "SELECT id, ts, trigger, person_count, no_helmet, no_vest, image FROM events"
    if only_violations:
        sql += " WHERE trigger = 'violation'"
    sql += " ORDER BY id DESC LIMIT ?"
    con = db()
    rows = con.execute(sql, (limit,)).fetchall()
    con.close()
    items = [
        {
            "id": r["id"],
            "ts": r["ts"],
            "trigger": r["trigger"],
            "person_count": r["person_count"],
            "no_helmet": r["no_helmet"],
            "no_vest": r["no_vest"],
            "image_url": r["image"],
        }
        for r in rows
    ]
    return {"items": items}


app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")
# 모든 API 라우트 뒤에 둬야 /api/* 를 가리지 않음
app.mount("/", StaticFiles(directory="/app/static", html=True), name="static")
