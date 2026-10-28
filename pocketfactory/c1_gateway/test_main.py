# C1 파이프라인 검사: C2·C3·C4를 가짜로 두고 프레임 하나가 대시보드 결과까지 가는지, 실패가 따로 세지는지 확인.
# 실행: docker compose run --rm --no-deps c1-gateway python -m c1_gateway.test_main
import base64
import json

import httpx
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import c1_gateway.main as main
from common.schema import InferRequest, InferResponse, PreprocessResponse, Result, Target

c3_fails = False


def fake_services(request: httpx.Request):
    path = request.url.path
    if path == "/process":
        return httpx.Response(200, text=PreprocessResponse(targets=[Target(cookie_id=1, line=2, box=(0, 0, 10, 10))]).model_dump_json())
    if path == "/infer":
        if c3_fails:
            return httpx.Response(500)
        meta = request.content.split(b'name="meta"\r\n\r\n')[1].split(b"\r\n--")[0]
        t = InferRequest.model_validate_json(meta).targets[0]
        res = Result(cookie_id=t.cookie_id, line=t.line, polygon=[(0, 0)], area=1, perimeter=1,
                     circularity=0.5, solidity=0.9, verdict="NG")
        return httpx.Response(200, text=InferResponse(results=[res]).model_dump_json())
    if path == "/render":
        return httpx.Response(200, content=b"marked")
    return httpx.Response(404)


def next_of(ws, kind):
    for _ in range(20):
        m = json.loads(ws.receive_text())
        if m["type"] == kind:
            return m
    raise AssertionError(f"{kind} 메시지가 오지 않음")


def test_pipeline():
    global c3_fails
    main.TRANSPORT = httpx.MockTransport(fake_services)
    with TestClient(main.app) as c, c.websocket_connect("/ws/dashboard") as dash:
        with c.websocket_connect("/ws/ingest?stream_id=sim") as ing:
            ing.send_bytes(b"jpeg-1")
            live = next_of(dash, "live")
            assert live["stream_id"] == "sim" and base64.b64decode(live["jpeg"]) == b"jpeg-1"
            res = next_of(dash, "result")
            assert res["frame"]["frame_id"] == 1
            assert res["results"][0]["verdict"] == "NG" and res["results"][0]["line"] == 2
            assert base64.b64decode(res["jpeg"]) == b"marked"
            assert set(res["timing"]) == {"c2", "c3", "c4", "total"}

            c3_fails = True
            ing.send_bytes(b"jpeg-2")
            for _ in range(50):
                s = c.get("/stats").json()
                if s["failed"]:
                    break
        assert s["frames_in"] == 2 and s["ng"] == 1 and s["failed"] == 1, s

        try:  # 대시보드에 그대로 찍히는 값이라 태그 같은 문자는 입구에서 거절
            with c.websocket_connect("/ws/ingest?stream_id=<img>"):
                raise AssertionError("잘못된 stream_id가 통과함")
        except WebSocketDisconnect:
            pass


if __name__ == "__main__":
    test_pipeline()
    print("ok")
