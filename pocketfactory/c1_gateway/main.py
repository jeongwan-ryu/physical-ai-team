# C1 Gateway: 프레임 수신, C2→C3→C4 호출, 대시보드 푸시 (설계 3장)
#
# 수신부 → 라이브 슬롯(대시보드별 1장)            → 방송부 → 대시보드
#        → C2 대기열 → C2 워커 1개 → 검사 대기열 → 검사 워커 N개(C3→C4) → 방송부
import asyncio
import base64
import io
import json
import os
import secrets
import time
from collections import deque
from contextlib import asynccontextmanager

import httpx
import qrcode
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect

from common.schema import FrameMeta, InferRequest, InferResponse, PreprocessResponse, RenderRequest

C2_URL = os.environ.get("C2_URL", "http://c2-preprocess:8000")
C3_URL = os.environ.get("C3_URL", "http://c3-lb:80")
C4_URL = os.environ.get("C4_URL", "http://c4-visualizer:8000")
INSPECT_WORKERS = int(os.environ.get("INSPECT_WORKERS") or 6)
INSPECT_QUEUE = int(os.environ.get("INSPECT_QUEUE") or 20)
C2_QUEUE = int(os.environ.get("C2_QUEUE") or 4)
TIMEOUT_C2 = 1.0
TIMEOUT_C3 = float(os.environ.get("TIMEOUT_C3") or 10)
TIMEOUT_C4 = 1.0
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
TRANSPORT = None  # 테스트에서 httpx.MockTransport로 바꿔 끼움

stats = {"frames_in": 0, "frames_dropped": 0, "c2_errors": 0, "c4_errors": 0,
         "ok": 0, "ng": 0, "skipped": 0, "failed": 0}
latency = {k: deque(maxlen=200) for k in ("c2", "c3", "c4", "total")}  # 최근 200건 평균
done_times = deque()  # 최근 판정 완료 시각, 처리량 계산용
frame_ids: dict[str, int] = {}
dashboards: set["Dashboard"] = set()


class Dashboard:
    """대시보드 연결 하나가 보낼 거리. 느린 화면이 다른 연결이나 파이프라인을 막지 않게 한다."""

    def __init__(self):
        self.live = None  # 라이브 슬롯: 최신 프레임 하나만 (덮어씀)
        self.results = deque(maxlen=100)  # 넘치면 가장 오래된 결과부터 버림
        self.wake = asyncio.Event()

    def push_live(self, msg):
        self.live = msg
        self.wake.set()

    def push_result(self, msg):
        self.results.append(msg)
        self.wake.set()


def b64(data: bytes) -> str:
    # ponytail: 대시보드로 JPEG를 base64 JSON으로 보냄(33% 커짐). 대역폭이 문제면 바이너리 프레임으로
    return base64.b64encode(data).decode()


async def post(url, meta, jpeg, timeout):
    r = await client.post(url, data={"meta": meta.model_dump_json()},
                          files={"image": ("frame.jpg", jpeg, "image/jpeg")}, timeout=timeout)
    r.raise_for_status()
    return r


async def c2_worker():
    # 반드시 1개: C2는 직전 프레임과 비교해 검사선 통과를 판단하므로 순서가 지켜져야 함
    while True:
        frame, jpeg = await c2_q.get()
        t = time.time()
        try:
            r = await post(f"{C2_URL}/process", frame, jpeg, TIMEOUT_C2)
            targets = PreprocessResponse.model_validate_json(r.content).targets
        except Exception:
            stats["c2_errors"] += 1
            continue
        timing = {"c2": time.time() - t}
        if not targets:
            continue
        try:
            inspect_q.put_nowait((frame, jpeg, targets, timing))
        except asyncio.QueueFull:
            stats["skipped"] += len(targets)  # 과자당 검사 기회는 이 프레임뿐이라 미검사로 기록


async def inspect_worker():
    while True:
        frame, jpeg, targets, timing = await inspect_q.get()
        t = time.time()
        try:
            r = await post(f"{C3_URL}/infer", InferRequest(frame=frame, targets=targets), jpeg, TIMEOUT_C3)
            results = InferResponse.model_validate_json(r.content).results
        except Exception:
            stats["failed"] += len(targets)
            continue
        timing["c3"] = time.time() - t
        t = time.time()
        try:
            r = await post(f"{C4_URL}/render", RenderRequest(frame=frame, results=results), jpeg, TIMEOUT_C4)
            marked = r.content
            timing["c4"] = time.time() - t
        except Exception:
            marked = None  # 마킹 없이 판정 결과만 보냄
            stats["c4_errors"] += 1
        timing["total"] = time.time() - frame.ts_recv  # 대기열에서 기다린 시간 포함

        now = time.time()
        for res in results:
            stats["ok" if res.verdict == "OK" else "ng"] += 1
            done_times.append(now)
        for k, v in timing.items():
            latency[k].append(v)
        msg = json.dumps({"type": "result", "frame": frame.model_dump(), "timing": timing,
                          "results": [res.model_dump() for res in results],
                          "jpeg": b64(marked) if marked else None})
        for d in dashboards:
            d.push_result(msg)


def snapshot():
    now = time.time()
    while done_times and done_times[0] < now - 10:
        done_times.popleft()
    return {**stats, "inspected": stats["ok"] + stats["ng"],
            "throughput": len(done_times) / 10,  # 최근 10초간 초당 판정 과자 수
            "latency": {k: sum(v) / len(v) if v else None for k, v in latency.items()},
            "queues": {"c2": c2_q.qsize(), "inspect": inspect_q.qsize()}}


@asynccontextmanager
async def lifespan(app):
    global client, c2_q, inspect_q
    client = httpx.AsyncClient(transport=TRANSPORT)  # 앱 전체가 하나를 공유해 연결 재사용
    c2_q = asyncio.Queue(C2_QUEUE)
    inspect_q = asyncio.Queue(INSPECT_QUEUE)
    tasks = [asyncio.create_task(c2_worker())]
    tasks += [asyncio.create_task(inspect_worker()) for _ in range(INSPECT_WORKERS)]
    yield
    for t in tasks:
        t.cancel()
    await client.aclose()


app = FastAPI(lifespan=lifespan)


@app.websocket("/ws/ingest")
async def ingest(ws: WebSocket, stream_id: str = "default"):
    """메시지 하나 = JPEG 한 장(바이너리). stream_id는 주소의 ?stream_id= 로 받음."""
    await ws.accept()
    try:
        while True:
            jpeg = await ws.receive_bytes()
            fid = frame_ids[stream_id] = frame_ids.get(stream_id, 0) + 1
            frame = FrameMeta(frame_id=fid, stream_id=stream_id, ts_recv=time.time())
            stats["frames_in"] += 1
            if dashboards:
                msg = json.dumps({"type": "live", "stream_id": stream_id, "frame_id": fid, "jpeg": b64(jpeg)})
                for d in dashboards:
                    d.push_live(msg)
            if c2_q.full():  # C2가 밀리면 가장 오래된 프레임을 버림
                c2_q.get_nowait()
                stats["frames_dropped"] += 1
            c2_q.put_nowait((frame, jpeg))
    except WebSocketDisconnect:
        pass


@app.websocket("/ws/dashboard")
async def dashboard(ws: WebSocket):
    """live(원본), result(판정+마킹 이미지), stats(1초마다) 메시지를 JSON 텍스트로 보냄."""
    await ws.accept()
    d = Dashboard()
    dashboards.add(d)
    last_stats = 0.0
    try:
        while True:
            try:
                await asyncio.wait_for(d.wake.wait(), 1)
            except asyncio.TimeoutError:
                pass
            d.wake.clear()
            if d.live:
                msg, d.live = d.live, None
                await ws.send_text(msg)
            while d.results:
                await ws.send_text(d.results.popleft())
            if time.time() - last_stats >= 1:
                last_stats = time.time()
                await ws.send_text(json.dumps({"type": "stats", **snapshot()}))
    except Exception:
        pass  # 끊긴 연결은 보낼 때 예외로 드러남
    finally:
        dashboards.discard(d)


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/stats")
def get_stats():
    return snapshot()


@app.get("/api/qr")
def qr():
    if not PUBLIC_BASE_URL:
        raise HTTPException(503, "PUBLIC_BASE_URL이 없습니다. scripts/make-cert.sh를 실행하세요.")
    stream_id = "phone-" + secrets.token_hex(2)
    url = f"{PUBLIC_BASE_URL}/capture.html?stream_id={stream_id}"
    buf = io.BytesIO()
    qrcode.make(url, box_size=8, border=2).save(buf, format="PNG")
    return {"url": url, "stream_id": stream_id, "qr_png": b64(buf.getvalue())}
