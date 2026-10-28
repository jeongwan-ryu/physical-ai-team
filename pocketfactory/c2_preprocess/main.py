# C2 Preprocess: 조명 보정, 과자 검출, 검사선 통과 선별 (설계 4장)
#
# 손에 든 폰(거치대 없음)도 받도록 추적을 흔들림에 강하게 만든다.
# - 화면 전체의 흔들림은 "모든 과자가 같이 움직인 양"으로 프레임마다 추정해 짝짓기에서 뺀다
# - 과자마다 트랙을 두고 트랙당 한 번만 검사한다. 흔들려서 검사선을 왔다 갔다 해도 중복 없음
# - 검사선을 지난 뒤 흔들림이 큰(블러) 프레임은 몇 프레임 기다렸다가 선명한 프레임으로 보낸다
# - 라인 번호는 매 프레임 과자들끼리의 위아래 순서로 매긴다 (폰이 기운 각도도 보정)
# 영상 자체를 보정(warp)하지 않으므로 박스는 그대로 원본 좌표다.
import os
import threading
import time
from dataclasses import dataclass, field

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, UploadFile

from common.schema import FrameMeta, PreprocessResponse, Target

SCAN_X_RATIO = float(os.getenv("SCAN_X_RATIO", "0.34"))
FLOW_SIGN = -1.0 if os.getenv("FLOW_DIRECTION", "left") == "left" else 1.0
EDGE_MARGIN = int(os.getenv("EDGE_MARGIN", "10"))

WORK_WIDTH = 640            # 검출은 이 폭으로 줄여서 하고 좌표만 원본으로 되돌림
HSV_LO = (5, 60, 70)        # 갈색~주황 과자 (OpenCV 색상 0~180)
HSV_HI = (35, 255, 255)
MATCH_TOL = 0.45            # 짝짓기 허용 거리, 과자 크기 대비
MAX_MISSED = 8              # 검출이 이만큼 끊겨도 트랙 유지 (블러 프레임 대비)
MIN_AGE = 3                 # 이만큼 짝지어진 트랙만 검사 (잠깐 잡힌 잡음 제외)
UPSTREAM_MARGIN = 0.5       # 검사선 앞으로 과자 크기의 이 비율 이상 떨어져 보인 적이 있어야 통과로 인정 (흔들림 왕복 방지)
GROUP_MARGIN = 0.5          # 다른 과자를 보낼 때 검사선 앞 과자 크기의 이 비율 안에 있으면 같은 열로 보고 함께 보냄
MAX_WAIT = 4                # 검사선을 지난 뒤 선명한 프레임을 기다리는 최대 프레임 수
SHARP_RATIO = 0.6           # 그 과자의 최고 선명도 대비 이 이상이면 선명하다고 봄
STEADY_RATIO = 0.15         # 직전 프레임 대비 흔들림이 과자 크기의 이 비율 이하면 안정
MIN_SPEED = 0.2             # 벨트 속도가 과자 크기/초의 이 비율 미만이면 멈춘 것으로 보고 검사 안 함
BOX_PAD = 0.08              # SAM 2 박스 프롬프트 여유
STREAM_TTL = 120            # 초, 이 시간 동안 프레임이 없으면 스트림 상태 삭제

CLAHE = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
K_OPEN = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
K_CLOSE = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))


@dataclass
class Det:
    pos: np.ndarray                          # 중심 (원본 좌표)
    box: tuple[float, float, float, float]   # 여유 없는 박스 (원본 좌표)
    size: float
    sharp: float


@dataclass
class Track:
    pos: np.ndarray
    size: float
    age: int = 1
    missed: int = 0
    seen_upstream: bool = False
    inspected: bool = False
    wait: int = 0
    best_sharp: float = 0.0
    drift: float = 0.0       # 흐름 방향으로 공통 움직임과 어긋난 양. 정지 물체(UI 등)를 걸러냄
    det: Det | None = None   # 이번 프레임에 짝지어진 검출


@dataclass
class StreamState:
    tracks: list[Track] = field(default_factory=list)
    next_cookie_id: int = 1
    n: int = 0                                  # 처리한 프레임 수
    last_frame_id: int = -1
    last_ts: float = 0.0
    seen_at: float = 0.0
    belt_vel: np.ndarray = field(default_factory=lambda: np.zeros(2))  # 벨트 속도(px/s), 흔들림의 장기 평균
    last_shake: np.ndarray = field(default_factory=lambda: np.zeros(2))
    size: float = 0.0                           # 과자 크기 대표값


def detect(img: np.ndarray) -> list[Det]:
    h, w = img.shape[:2]
    s = min(1.0, WORK_WIDTH / w)
    small = cv2.resize(img, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else img
    lab = cv2.cvtColor(small, cv2.COLOR_BGR2LAB)
    lab[..., 0] = CLAHE.apply(lab[..., 0])
    small = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(cv2.GaussianBlur(small, (5, 5), 0), cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, HSV_LO, HSV_HI)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, K_OPEN)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, K_CLOSE)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    sw = small.shape[1]
    dets = []
    for c in contours:
        x, y, bw, bh = cv2.boundingRect(c)
        side = max(bw, bh)
        if not (0.02 * sw <= side <= 0.35 * sw) or side > 2.5 * min(bw, bh):
            continue
        if cv2.contourArea(c) < 0.4 * bw * bh:
            continue
        sharp = float(cv2.Laplacian(gray[y:y + bh, x:x + bw], cv2.CV_64F).var())
        dets.append(Det(
            pos=np.array([(x + bw / 2) / s, (y + bh / 2) / s]),
            box=(x / s, y / s, (x + bw) / s, (y + bh) / s),
            size=side / s,
            sharp=sharp,
        ))
    return dets


def estimate_shift(tracks: list[Track], dets: list[Det], prior: np.ndarray, tol: float) -> tuple[np.ndarray, int]:
    """모든 과자가 함께 움직인 양(벨트 + 카메라 흔들림). 트랙→검출 쌍마다 후보를 만들고 가장 많이 맞는 것을 고름."""
    live = [t for t in tracks if t.missed == 0] or tracks    # 끊겼던 트랙은 위치가 부정확해서 빼고 추정
    if not live or not dets:
        return prior, 0
    P = np.array([t.pos for t in live])
    D = np.array([d.pos for d in dets])
    cands = (D[None, :, :] - P[:, None, :]).reshape(-1, 2)
    pred = P[None, :, :] + cands[:, None, :]                                     # (C, T, 2)
    dist = np.linalg.norm(pred[:, :, None, :] - D[None, None, :, :], axis=3)    # (C, T, N)
    inliers = (dist.min(axis=2) < tol).sum(axis=1)
    # 과자가 일정 간격으로 놓여 한 칸 밀린 후보도 거의 다 맞으므로, 예상 이동량에서 멀어질수록 크게 깎음
    off = np.linalg.norm(cands - prior, axis=1)
    k = int(np.argmax(inliers - off / tol))
    if inliers[k] < 0.5 * min(len(P), len(D)):
        k = int(np.argmax(inliers - off / (4 * tol)))       # 폰이 확 움직여 예상이 크게 빗나간 프레임
    best = cands[k]
    near = np.linalg.norm(P[:, None, :] + best - D[None, :, :], axis=2)
    ti, di = np.nonzero(near < tol)
    if len(ti) == 0:
        return prior, 0
    return np.median(D[di] - P[ti], axis=0), int(inliers.max())


def associate(tracks: list[Track], dets: list[Det], shift: np.ndarray, tol: float) -> list[Det]:
    pairs = sorted(
        (float(np.linalg.norm(t.pos + shift - d.pos)), ti, di)
        for ti, t in enumerate(tracks) for di, d in enumerate(dets)
    )
    used_t, used_d = set(), set()
    for dist, ti, di in pairs:
        if dist >= tol:
            break
        if ti in used_t or di in used_d:
            continue
        used_t.add(ti)
        used_d.add(di)
        tracks[ti].det = dets[di]
    return [d for di, d in enumerate(dets) if di not in used_d]


def lane_numbers(dets: list[Det], size: float) -> list[int]:
    """이번 프레임 과자들끼리 위아래로 묶어 라인 번호를 매김 (위에서부터 1). 폰이 기운 만큼은 기울기로 보정."""
    if not dets:
        return []
    P = np.array([d.pos for d in dets])
    dx = P[None, :, 0] - P[:, None, 0]
    dy = P[None, :, 1] - P[:, None, 1]
    same = (np.abs(dy) < 0.5 * size) & (np.abs(dx) > 1.5 * size)   # 같은 라인으로 보이는 쌍
    slope = float(np.median(dy[same] / dx[same])) if same.any() else 0.0
    v = P[:, 1] - slope * P[:, 0]
    order = np.argsort(v)
    lanes = [0] * len(dets)
    n = 1
    for i, k in enumerate(order):
        if i and v[k] - v[order[i - 1]] > 0.6 * size:
            n += 1
        lanes[k] = n
    return lanes


def step(st: StreamState, frame: FrameMeta, img: np.ndarray) -> list[Target]:
    h, w = img.shape[:2]
    ts = frame.ts_capture if frame.ts_capture is not None else frame.ts_recv
    dt = ts - st.last_ts
    # 프레임 순서가 뒤집히거나 1초 넘게 끊기면 추적을 새로 시작 (cookie_id는 이어서)
    if frame.frame_id <= st.last_frame_id or not (0 < dt < 1.0):
        st.tracks = []
        st.last_shake = np.zeros(2)
        dt = 1 / 15
    st.last_frame_id, st.last_ts, st.seen_at = frame.frame_id, ts, time.time()
    st.n += 1

    dets = detect(img)
    if dets:
        med = float(np.median([d.size for d in dets]))
        st.size = med if st.size == 0 else 0.9 * st.size + 0.1 * med
        dets = [d for d in dets if 0.5 * st.size <= d.size <= 1.6 * st.size]
    if st.size == 0:
        return []
    tol = MATCH_TOL * st.size

    belt_step = st.belt_vel * dt
    shift, n_in = estimate_shift(st.tracks, dets, belt_step + 0.5 * st.last_shake, tol)
    if n_in >= 2:
        st.belt_vel = 0.95 * st.belt_vel + 0.05 * shift / dt
        belt_step = st.belt_vel * dt
    shake = shift - belt_step
    st.last_shake = shake

    for t in st.tracks:
        t.det = None
    rest = associate(st.tracks, dets, shift, tol)
    # 끊겼던 트랙은 위치 오차가 커서 한 번 더 넓게 찾음. 같은 과자에 새 트랙이 생겨 중복 검사되는 것을 막음
    rest = associate([t for t in st.tracks if t.det is None and t.missed > 0], rest, shift, 2 * tol)
    for d in rest:
        st.tracks.append(Track(pos=d.pos.copy(), size=d.size, det=d, age=0))
    lane_of = {id(d): n for d, n in zip(dets, lane_numbers(dets, st.size))}

    moving = abs(st.belt_vel[0]) >= MIN_SPEED * st.size and st.belt_vel[0] * FLOW_SIGN > 0
    scan_x = SCAN_X_RATIO * w

    shake_len = float(np.linalg.norm(shake))
    cands = []      # (트랙, 검사선을 지났는지, 보낼 때가 됐는지). 조건은 다 맞고 검사선 근처에 있는 과자
    for t in st.tracks:
        d = t.det
        if d is None:
            t.missed += 1
            t.pos = t.pos + shift
            continue
        if t.age > 0:
            t.drift = 0.9 * t.drift + float(d.pos[0] - t.pos[0] - shift[0])
        t.pos, t.size, t.missed = d.pos, d.size, 0
        t.age += 1

        along = (d.pos[0] - scan_x) * FLOW_SIGN          # 검사선을 지난 거리 (앞이면 음수)
        downstream = along > 0
        if along < -UPSTREAM_MARGIN * t.size:
            t.seen_upstream = True
        sharp_ok = d.sharp >= SHARP_RATIO * t.best_sharp
        t.best_sharp = max(0.97 * t.best_sharp, d.sharp)

        x1, y1, x2, y2 = d.box
        inside = x1 >= EDGE_MARGIN and y1 >= EDGE_MARGIN and x2 <= w - EDGE_MARGIN and y2 <= h - EDGE_MARGIN
        if t.inspected or not (along > -GROUP_MARGIN * t.size and t.seen_upstream and inside and moving
                               and t.age >= MIN_AGE):
            continue
        if abs(t.drift) > 0.5 * t.size:     # 벨트와 같이 움직이지 않는 물체
            continue
        due = False
        if downstream:
            t.wait += 1
            due = (sharp_ok and shake_len <= STEADY_RATIO * t.size) or t.wait > MAX_WAIT
        cands.append((t, downstream, due))

    # 검사선을 지난 과자 하나라도 보낼 때가 되면, 검사선 바로 앞까지 온 과자도 같은 프레임으로 함께 보냄.
    # 따로 보내면 한 열이 1~3프레임에 나뉘어 C3를 여러 번 부르고, 대시보드에 같은 장면 카드가 라인별로 쪼개져 쌓임
    targets = []
    if any(due for _, _, due in cands):
        for t, _, _ in cands:
            t.inspected = True
            x1, y1, x2, y2 = t.det.box
            pad = BOX_PAD * t.size
            targets.append(Target(
                cookie_id=st.next_cookie_id,
                line=lane_of[id(t.det)],
                box=(max(0.0, x1 - pad), max(0.0, y1 - pad), min(w - 1.0, x2 + pad), min(h - 1.0, y2 + pad)),
            ))
            st.next_cookie_id += 1

    st.tracks = [
        t for t in st.tracks
        if t.missed <= MAX_MISSED and -t.size < t.pos[0] < w + t.size and -t.size < t.pos[1] < h + t.size
    ]
    return targets


app = FastAPI()
streams: dict[str, StreamState] = {}
lock = threading.Lock()


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/process", response_model=PreprocessResponse)
def process(meta: str = Form(...), image: UploadFile = File(...)):
    frame = FrameMeta.model_validate_json(meta)
    img = cv2.imdecode(np.frombuffer(image.file.read(), np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return PreprocessResponse(targets=[])
    with lock:
        now = time.time()
        for sid in [k for k, v in streams.items() if now - v.seen_at > STREAM_TTL]:
            del streams[sid]
        st = streams.setdefault(frame.stream_id, StreamState())
        return PreprocessResponse(targets=step(st, frame, img))
