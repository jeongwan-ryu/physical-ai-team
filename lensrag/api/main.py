"""PC 대시보드, QR 연동, 모바일 촬영 페이지, 업로드, 검색 중계를 맡는 api 서버.

실행: uvicorn api.main:app --host 0.0.0.0 --port 8000
Supabase 호출은 동기 클라이언트라서 해당 엔드포인트는 일반 def로 둔다 (FastAPI가 스레드풀에서 실행).
"""
import asyncio
import base64
import io
import os
import secrets
import uuid
from pathlib import Path

import httpx
import qrcode
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from shared.sb import sb

PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
RAG_URL = os.environ.get("RAG_URL", "http://rag:8001").rstrip("/")
RAG_MOCK = os.environ.get("RAG_MOCK", "") == "1"

STATIC = Path(__file__).parent / "static"
BUCKET = "uploads"
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
PASSAGE_COLUMNS = "id, card_no, filename, status, content, error, created_at"  # embedding은 절대 내려주지 않음

MOCK_RESPONSE = {
    "answer": "(mock) Q3 총 처리량은 1,482,600개입니다. [카드 004]",
    "sources": [
        {"id": 0, "card_no": 4, "content": "Total throughput for Q3 reached 1,482,600 units ...", "score": 0.87}
    ],
}

app = FastAPI()


def make_qr_png_base64(text: str) -> str:
    img = qrcode.make(text, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def get_session(session_id: str) -> dict | None:
    res = sb.table("sessions").select("id, connected").eq("id", session_id).limit(1).execute()
    return res.data[0] if res.data else None


# ---------- 페이지 ----------

@app.get("/")
def dashboard():
    return FileResponse(STATIC / "dashboard.html")


@app.get("/m/{session_id}")
def mobile(session_id: str):
    if not get_session(session_id):
        return HTMLResponse(
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<h2 style='font-family:sans-serif;padding:24px'>세션을 찾을 수 없습니다.<br>"
            "PC 화면의 QR을 다시 찍어주세요.</h2>",
            status_code=404,
        )
    sb.table("sessions").update({"connected": True}).eq("id", session_id).execute()
    return FileResponse(STATIC / "mobile.html")


# ---------- 세션 ----------

@app.post("/api/sessions")
def create_session():
    session_id = secrets.token_urlsafe(6)
    sb.table("sessions").insert({"id": session_id}).execute()
    url = f"{PUBLIC_BASE_URL}/m/{session_id}"
    return {"session_id": session_id, "url": url, "qr_png": make_qr_png_base64(url)}


@app.get("/api/sessions/{session_id}")
def read_session(session_id: str):
    session = get_session(session_id)
    if not session:
        raise HTTPException(404, "세션이 없습니다.")
    return {"session_id": session["id"], "connected": bool(session["connected"])}


# ---------- 업로드 ----------

@app.post("/api/upload")
def upload(session_id: str, file: UploadFile = File(...)):
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(400, "이미지 파일만 올릴 수 있습니다.")
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "파일이 너무 큽니다 (최대 15MB).")
    if not data:
        raise HTTPException(400, "빈 파일입니다.")
    if not get_session(session_id):
        raise HTTPException(404, "세션이 없습니다. QR을 다시 찍어주세요.")

    # 한글 파일명은 Storage 키로 쓰지 않고 uuid + 원래 확장자만 사용
    ext = Path(file.filename or "").suffix.lower() or ".jpg"
    image_path = f"{uuid.uuid4()}{ext}"
    sb.storage.from_(BUCKET).upload(image_path, data, {"content-type": file.content_type})

    res = sb.table("passages").insert({
        "session_id": session_id,
        "filename": file.filename,
        "image_path": image_path,
        "status": "uploaded",
    }).execute()
    return {"id": res.data[0]["id"], "status": "uploaded"}


# ---------- 목록 ----------

@app.get("/api/passages")
def list_passages(session_id: str | None = None):
    query = sb.table("passages").select(PASSAGE_COLUMNS).order("created_at", desc=True)
    if session_id:
        query = query.eq("session_id", session_id)
    else:
        query = query.limit(50)
    return query.execute().data


# ---------- 검색 중계 ----------

@app.post("/api/search")
async def search(request: Request):
    body = await request.json()
    if RAG_MOCK:
        await asyncio.sleep(1)
        return MOCK_RESPONSE

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(f"{RAG_URL}/search", json=body)
    except httpx.TimeoutException:
        return JSONResponse({"detail": "검색 서버(rag) 응답이 30초 안에 오지 않았습니다."}, status_code=502)
    except httpx.HTTPError as e:
        return JSONResponse({"detail": f"검색 서버(rag)에 연결할 수 없습니다: {e}"}, status_code=502)

    if res.status_code != 200:
        return JSONResponse(
            {"detail": f"검색 서버(rag) 오류 {res.status_code}: {res.text[:300]}"}, status_code=502
        )
    return res.json()
