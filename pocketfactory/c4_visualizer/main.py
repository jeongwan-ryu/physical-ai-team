# C4 Visualizer: 원본 마킹, 판정 이력 저장 (설계 6장)
import os
import sqlite3
import threading
import time
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, Response, UploadFile
from PIL import Image, ImageDraw, ImageFont

from common.schema import RenderRequest, Result

DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
DEFECT_DIR = DATA_DIR / "defects"
JPEG_QUALITY = 85
NG_COLOR = (40, 40, 230)       # BGR
OK_COLOR = (90, 200, 90)
NG_ALPHA = 0.35                # 불량 마스크 투명도
FONT_PATHS = [
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",   # Dockerfile에서 설치
    "C:/Windows/Fonts/malgunbd.ttf",                         # 로컬 테스트용
]

DEFECT_DIR.mkdir(parents=True, exist_ok=True)
# 검사 워커 여러 개가 동시에 부르므로 연결 하나를 잠금으로 보호
db = sqlite3.connect(DATA_DIR / "inspections.db", check_same_thread=False)
db.execute("PRAGMA journal_mode=WAL")
db.execute("""
    CREATE TABLE IF NOT EXISTS inspections (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        stream_id   TEXT    NOT NULL,   -- frame_id, cookie_id가 스트림별 번호라 함께 저장
        frame_id    INTEGER NOT NULL,
        cookie_id   INTEGER NOT NULL,
        line        INTEGER NOT NULL,
        verdict     TEXT    NOT NULL,
        circularity REAL    NOT NULL,
        solidity    REAL    NOT NULL,
        ts_capture  REAL,
        ts_done     REAL    NOT NULL,
        image_path  TEXT
    )
""")
db.commit()
db_lock = threading.Lock()
_fonts: dict[int, ImageFont.FreeTypeFont] = {}


def font(size: int):
    if size not in _fonts:
        path = next((p for p in FONT_PATHS if Path(p).exists()), None)
        _fonts[size] = ImageFont.truetype(path, size) if path else ImageFont.load_default(size)
    return _fonts[size]


def mark(img: np.ndarray, results: list[Result]) -> np.ndarray:
    h, w = img.shape[:2]
    thick = max(2, round(min(w, h) / 240))
    polys = [np.round(np.array(r.polygon)).astype(np.int32) for r in results]

    # 불량은 빨간 반투명 마스크 + 굵은 외곽선, 정상은 초록 외곽선
    overlay = img.copy()
    for r, p in zip(results, polys):
        if r.verdict == "NG" and len(p) >= 3:
            cv2.fillPoly(overlay, [p], NG_COLOR, cv2.LINE_AA)
    img = cv2.addWeighted(overlay, NG_ALPHA, img, 1 - NG_ALPHA, 0)
    for r, p in zip(results, polys):
        if len(p) >= 2:
            ng = r.verdict == "NG"
            cv2.polylines(img, [p], True, NG_COLOR if ng else OK_COLOR, thick * 2 if ng else thick, cv2.LINE_AA)

    # 한글은 OpenCV putText가 못 그리므로 텍스트만 Pillow로
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)).convert("RGBA")
    layer = Image.new("RGBA", pil.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    f = font(max(14, round(h / 45)))
    pad = 4
    for r, p in zip(results, polys):
        ng = r.verdict == "NG"
        text = f"라인 {r.line} · {'불량' if ng else '정상'}\n원형도 {r.circularity:.3f}\n솔리디티 {r.solidity:.3f}"
        left, top, right, bottom = draw.multiline_textbbox((0, 0), text, font=f, spacing=2)
        tw, th = right - left + 2 * pad, bottom - top + 2 * pad
        if len(p):
            x, y = int(p[:, 0].min()), int(p[:, 1].min()) - th - thick
            if y < 0:                                   # 위에 자리가 없으면 과자 아래에
                y = int(p[:, 1].max()) + thick
        else:
            x, y = 0, 0
        x, y = min(max(0, x), max(0, w - tw)), min(max(0, y), max(0, h - th))
        bg = (*NG_COLOR[::-1], 210) if ng else (20, 20, 20, 170)
        draw.rectangle((x, y, x + tw, y + th), fill=bg)
        draw.multiline_text((x + pad - left, y + pad - top), text, font=f, fill=(255, 255, 255, 255), spacing=2)
    pil = Image.alpha_composite(pil, layer).convert("RGB")
    return cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)


app = FastAPI()


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/render")
def render(meta: str = Form(...), image: UploadFile = File(...)):
    req = RenderRequest.model_validate_json(meta)
    raw = image.file.read()
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        out = raw                                       # 디코드 실패면 받은 그대로 돌려줌
    else:
        out = cv2.imencode(".jpg", mark(img, req.results), [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])[1].tobytes()

    f = req.frame
    rows = []
    for r in req.results:
        path = None
        if r.verdict == "NG":
            path = DEFECT_DIR / f"{f.stream_id}_{f.frame_id}_{r.cookie_id}.jpg"
            path.write_bytes(out)
            path = str(path)
        rows.append((f.stream_id, f.frame_id, r.cookie_id, r.line, r.verdict,
                     r.circularity, r.solidity, f.ts_capture, time.time(), path))
    with db_lock:
        db.executemany(
            "INSERT INTO inspections (stream_id, frame_id, cookie_id, line, verdict, circularity, solidity,"
            " ts_capture, ts_done, image_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        db.commit()
    return Response(out, media_type="image/jpeg")
