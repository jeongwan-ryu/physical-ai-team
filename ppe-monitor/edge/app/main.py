"""edge 메인 루프: 캡처 → YOLO 추론 → 착용 판정 → server 전송 (docs/interface.md 기준)."""
import json
import os
import sys
import time
from datetime import datetime, timezone

import cv2
import numpy as np
import requests
from ultralytics import YOLO

# --- 환경변수 (interface 7장) ---
DEVICE_ID = os.environ.get("DEVICE_ID", "pi-01")
DEVICE_KEY = os.environ.get("DEVICE_KEY", "change-me")
SERVER_URL = os.environ.get("SERVER_URL", "http://host.docker.internal")
SOURCE = os.environ.get("SOURCE", "/ultralytics/ultralytics/assets/bus.jpg")
MODEL_PATH = os.environ.get("MODEL_PATH", "/models/best.pt")
IMGSZ = int(os.environ.get("IMGSZ", "640"))
CONF_TH = float(os.environ.get("CONF_TH", "0.4"))
HEAD_RATIO = float(os.environ.get("HEAD_RATIO", "0.3"))
CONFIRM_FRAMES = int(os.environ.get("CONFIRM_FRAMES", "3"))
REPORT_INTERVAL_S = float(os.environ.get("REPORT_INTERVAL_S", "5"))
FRAME_PUSH_INTERVAL_S = float(os.environ.get("FRAME_PUSH_INTERVAL_S", "1"))

EVENTS_LOG = "/data/events.jsonl"
HEADERS = {"X-Device-Key": DEVICE_KEY}
REQUIRED = ("Person", "Hardhat", "Safety Vest")

# --- 착용 판정: B의 compliance.py가 완성되면 그걸 쓰고, 아니면 임시 판정(interface 5.3) ---
try:
    from compliance import Debouncer, judge
    print("[edge] compliance.py 사용")
except ImportError:
    print("[edge] compliance.py 미완성 → main.py 임시 판정 사용")

    def _center_in(box, person, top, bottom):
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        px1, py1, px2, py2 = person
        h = py2 - py1
        return px1 <= cx <= px2 and py1 + h * top <= cy <= py1 + h * bottom

    def judge(dets, conf_th, head_ratio):
        dets = [d for d in dets if d[1] >= conf_th]
        hats = [b for n, c, b in dets if n == "Hardhat"]
        vests = [b for n, c, b in dets if n == "Safety Vest"]
        persons = []
        for n, c, b in dets:
            if n != "Person":
                continue
            persons.append({
                "bbox": [int(v) for v in b],
                "conf": round(float(c), 3),
                "helmet": any(_center_in(h, b, 0.0, head_ratio) for h in hats),
                "vest": any(_center_in(v, b, 0.2, 0.7) for v in vests),
            })
        return persons

    class Debouncer:
        def __init__(self, confirm_frames):
            self.n = confirm_frames
            self.state = False
            self.count = 0

        def update(self, violating):
            if violating == self.state:
                self.count = 0
                return False
            self.count += 1
            if self.count >= self.n:
                self.state = violating
                self.count = 0
                return violating
            return False


def now_ts():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def capture():
    """프레임 1장. 실패하면 None."""
    if SOURCE.startswith("http"):
        try:
            r = requests.get(SOURCE, timeout=3)
            r.raise_for_status()
            return cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
        except Exception as e:
            print(f"[edge] 캡처 실패: {e}")
            return None
    return cv2.imread(SOURCE)


def draw(frame, persons):
    img = frame.copy()
    for p in persons:
        ok = p["helmet"] and p["vest"]
        color = (0, 200, 0) if ok else (0, 0, 255)
        x1, y1, x2, y2 = p["bbox"]
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        label = f"H:{'O' if p['helmet'] else 'X'} V:{'O' if p['vest'] else 'X'}"
        cv2.putText(img, label, (x1, max(y1 - 6, 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
    return img


def to_jpeg(img):
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return buf.tobytes() if ok else None


def send_event(meta, jpeg=None):
    meta_str = json.dumps(meta, ensure_ascii=False)
    try:
        with open(EVENTS_LOG, "a", encoding="utf-8") as f:
            f.write(meta_str + "\n")
    except Exception as e:
        print(f"[edge] events.jsonl 기록 실패: {e}")
    files = {"meta": (None, meta_str)}
    if jpeg is not None:
        files["image"] = ("frame.jpg", jpeg, "image/jpeg")
    try:
        r = requests.post(f"{SERVER_URL}/api/events", headers=HEADERS, files=files, timeout=5)
        print(f"[edge] {meta['trigger']} 전송 → {r.status_code}")
    except Exception as e:
        print(f"[edge] {meta['trigger']} 전송 실패: {e}")


def push_frame(jpeg):
    try:
        requests.put(f"{SERVER_URL}/api/frame", data=jpeg, timeout=3,
                     headers={**HEADERS, "Content-Type": "image/jpeg"})
    except Exception:
        pass


def main():
    model = YOLO(MODEL_PATH)
    names = model.names
    missing = [n for n in REQUIRED if n not in names.values()]
    if missing:
        print(f"[edge] 모델에 필요한 클래스 없음: {missing} / names={names}")
        sys.exit(1)
    print(f"[edge] 시작 SOURCE={SOURCE} MODEL={MODEL_PATH} IMGSZ={IMGSZ} SERVER={SERVER_URL}")

    debouncer = Debouncer(CONFIRM_FRAMES)
    last_report = 0.0
    last_push = 0.0

    while True:
        t0 = time.time()
        frame = capture()
        if frame is None:
            time.sleep(1)
            continue
        ts = now_ts()
        h, w = frame.shape[:2]

        result = model(frame, imgsz=IMGSZ, verbose=False)[0]
        dets = [
            (names[int(c)], float(cf), xyxy.tolist())
            for c, cf, xyxy in zip(result.boxes.cls, result.boxes.conf, result.boxes.xyxy)
        ]
        persons = judge(dets, CONF_TH, HEAD_RATIO)
        violators = sum(1 for p in persons if not (p["helmet"] and p["vest"]))
        drawn = draw(frame, persons)
        jpeg = None

        now = time.time()
        if now - last_push >= FRAME_PUSH_INTERVAL_S:
            jpeg = to_jpeg(drawn)
            if jpeg:
                push_frame(jpeg)
            last_push = now

        meta = {"device_id": DEVICE_ID, "ts": ts, "frame_w": w, "frame_h": h, "persons": persons}

        if debouncer.update(violators >= 1):
            jpeg = jpeg or to_jpeg(drawn)
            send_event({**meta, "trigger": "violation"}, jpeg)

        if now - last_report >= REPORT_INTERVAL_S:
            send_event({**meta, "trigger": "interval"})
            last_report = now

        dt = time.time() - t0
        print(f"[edge] persons={len(persons)} violators={violators} {dt * 1000:.0f}ms ({1 / dt:.1f} FPS)")


if __name__ == "__main__":
    main()
