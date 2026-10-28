"""C3 단독 판정 확인 (설계 11장 1단계).
시뮬레이터에서 정지 후 S(프레임 PNG)와 L(정답 라벨 JSON)로 저장한 쌍을 C3 /infer로 보내 정답과 비교한다.
C2가 없으므로 라벨의 bbox를 박스 프롬프트로 쓰고, 라벨의 외곽선과 C3 외곽선의 IoU로 마스크 품질을 본다.

C3 컨테이너 안에서 실행 (cv2·numpy가 있음):
  docker run --rm -v $PWD/weights:/weights:ro -v $PWD/scripts:/scripts:ro -v {저장 폴더}:/data \
    {C3 이미지} sh -c "uvicorn c3_sam2.main:app --port 8000 & python /scripts/check_c3.py /data/frame_….png /data/labels_….json"
결과 이미지(정답 외곽선 회색, C3 외곽선 초록=OK/빨강=NG)는 프레임 옆에 check_….png로 저장된다.
"""
import argparse
import json
import time
import urllib.request
import uuid
from pathlib import Path

import cv2
import numpy as np

p = argparse.ArgumentParser()
p.add_argument("frame")
p.add_argument("labels")
p.add_argument("--url", default="http://localhost:8000")
p.add_argument("--edge-margin", type=float, default=10, help="가장자리에서 이만큼 안 떨어진 과자는 제외 (C2 EDGE_MARGIN)")
args = p.parse_args()

frame = cv2.imread(args.frame, cv2.IMREAD_COLOR)
labels = json.loads(Path(args.labels).read_text())
h, w = frame.shape[:2]

# 화면 가장자리에 걸려 잘린 과자는 불량처럼 보이므로 C2처럼 제외
anns = [a for a in labels["annotations"]
        if a["bbox"][0] > args.edge_margin and a["bbox"][1] > args.edge_margin
        and a["bbox"][0] + a["bbox"][2] < w - args.edge_margin and a["bbox"][1] + a["bbox"][3] < h - args.edge_margin]
targets = [{"cookie_id": a["id"], "line": a["line"],
            "box": [a["bbox"][0], a["bbox"][1], a["bbox"][0] + a["bbox"][2], a["bbox"][1] + a["bbox"][3]]} for a in anns]
meta = {"frame": {"frame_id": 1, "stream_id": "check", "ts_recv": time.time()}, "targets": targets}

# C1이 보내는 것과 같은 JPEG로 보냄
jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tobytes()
b = uuid.uuid4().hex
body = (f"--{b}\r\nContent-Disposition: form-data; name=\"meta\"\r\n\r\n{json.dumps(meta)}\r\n"
        f"--{b}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"frame.jpg\"\r\n"
        f"Content-Type: image/jpeg\r\n\r\n").encode() + jpg + f"\r\n--{b}--\r\n".encode()

for _ in range(60):  # 모델 로딩 대기
    try:
        urllib.request.urlopen(f"{args.url}/health")
        break
    except Exception:
        time.sleep(1)

req = urllib.request.Request(f"{args.url}/infer", data=body,
                             headers={"Content-Type": f"multipart/form-data; boundary={b}"})
t = time.time()
results = json.load(urllib.request.urlopen(req))["results"]
elapsed = time.time() - t


def fill(points):
    m = np.zeros((h, w), np.uint8)
    if len(points) >= 3:
        cv2.fillPoly(m, [np.round(np.array(points, np.float32)).astype(np.int32)], 1)
    return m


out = frame.copy()
rows = []
for a, r in zip(anns, results):
    truth = np.array(a["segmentation"][0], np.float32).reshape(-1, 2)
    gt, pred = fill(truth), fill(r["polygon"])
    iou = (gt & pred).sum() / max((gt | pred).sum(), 1)
    expect = "OK" if a["category"] == "round" else "NG"
    rows.append((a, r, iou, expect))
    cv2.polylines(out, [np.round(truth).astype(np.int32)], True, (160, 160, 160), 1)
    if r["polygon"]:
        color = (80, 200, 80) if r["verdict"] == "OK" else (60, 60, 230)
        cv2.polylines(out, [np.round(np.array(r["polygon"])).astype(np.int32)], True, color, 2)
    x, y = int(a["bbox"][0]), int(a["bbox"][1])
    cv2.putText(out, f"{a['id']}", (x, max(y - 4, 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

print(f"{Path(args.frame).name}  과자 {len(anns)}개 (가장자리 제외 {len(labels['annotations']) - len(anns)}개)  "
      f"추론 {elapsed:.2f}s")
print(f"{'id':>4} {'line':>4} {'정답':<8} {'원형도':>7} {'솔리디티':>8} {'IoU':>6}  판정")
for a, r, iou, expect in sorted(rows, key=lambda x: (x[3], x[0]["id"])):
    mark = "" if r["verdict"] == expect else "  <-- 틀림"
    print(f"{a['id']:>4} {a['line']:>4} {a['defect_type'] or 'normal':<8} {r['circularity']:7.3f} "
          f"{r['solidity']:8.3f} {iou:6.3f}  {r['verdict']}{mark}")

ok = [r for _, r, _, e in rows if e == "OK"]
ng = [r for _, r, _, e in rows if e == "NG"]
miss = sum(r["verdict"] != e for _, r, _, e in rows)
print(f"\n정상 {len(ok)}개: 원형도 최소 {min((r['circularity'] for r in ok), default=0):.3f}, "
      f"솔리디티 최소 {min((r['solidity'] for r in ok), default=0):.3f}")
print(f"불량 {len(ng)}개: 원형도 최대 {max((r['circularity'] for r in ng), default=0):.3f}, "
      f"솔리디티 최대 {max((r['solidity'] for r in ng), default=0):.3f}")
print(f"틀린 판정 {miss}개, IoU 최소 {min((i for _, _, i, _ in rows), default=0):.3f}")

save = Path(args.frame).with_name(f"check_{Path(args.frame).stem}.png")
cv2.imwrite(str(save), out)
print(f"결과 이미지: {save}")
