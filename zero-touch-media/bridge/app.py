# C 담당: MQTT 구독 → presence → GET /events (SSE) + /web 정적 서빙, 포트 8080
import functools
import json
import os
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import paho.mqtt.client as mqtt

from presence import Presence

TOPIC = "ztmc/cam1/face"  # README 계약 1

presence = Presence(float(os.environ["SCORE_TH"]), int(os.environ["PRESENT_MS"]),
                    int(os.environ["ABSENT_MS"]), int(os.environ["STALE_MS"]))
cond = threading.Condition()  # presence 보호 + 상태 변화 알림


def step(score=None):
    with cond:
        old = presence.state
        if presence.update(time.monotonic() * 1000, score) != old:
            print("state:", presence.state, flush=True)
            cond.notify_all()


def on_connect(client, userdata, flags, reason_code, properties):
    print("mqtt connect:", reason_code, flush=True)
    client.subscribe(TOPIC)  # 재연결 시에도 재구독


def on_message(client, userdata, msg):
    try:
        score = float(json.loads(msg.payload)["score"])
    except (ValueError, KeyError, TypeError):
        print("bad payload:", msg.payload[:100], flush=True)
        return
    step(score)


def tick():
    while True:
        time.sleep(0.1)
        step()


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?")[0] != "/events":
            return super().do_GET()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        sent = None
        try:
            while True:
                with cond:
                    cond.wait_for(lambda: presence.state != sent)
                    sent = presence.state
                self.wfile.write(f'data: {{"state":"{sent}"}}\n\n'.encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass  # ponytail: 끊긴 클라이언트는 다음 상태 변화 때 감지됨. 필요하면 keepalive 주석 추가


if __name__ == "__main__":
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect, client.on_message = on_connect, on_message
    client.connect_async(os.environ["MQTT_HOST"], 1883)
    client.loop_start()  # 브로커가 늦게 떠도 자동 재시도
    threading.Thread(target=tick, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", 8080), functools.partial(Handler, directory="/web"))
    server.serve_forever()
