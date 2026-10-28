# C3 SAM 2: 마스크 추출, 원형도·솔리디티 판정 (설계 5장)
import math
import os
import threading
from contextlib import asynccontextmanager

import cv2
import numpy as np
import torch
from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile

from common.schema import InferRequest, InferResponse, Result

SAM2_MODEL = os.getenv("SAM2_MODEL", "sam2.1_hiera_tiny")
SAM2_IMAGE_SIZE = int(os.getenv("SAM2_IMAGE_SIZE", "512"))  # SAM 2 입력 크기(32의 배수). 원래 1024, 512면 임베딩이 약 4배 빠름
DEVICE = os.getenv("DEVICE", "cpu")
TORCH_THREADS = int(os.getenv("TORCH_THREADS", "0"))  # 0이면 torch 기본값
CIRC_THRESHOLD = float(os.getenv("CIRC_THRESHOLD", "0.96"))
SOLIDITY_THRESHOLD = float(os.getenv("SOLIDITY_THRESHOLD", "0.985"))

# 체크포인트 이름 → sam2 패키지에 들어 있는 설정 파일
CONFIGS = {
    "sam2.1_hiera_tiny": "configs/sam2.1/sam2.1_hiera_t.yaml",
    "sam2.1_hiera_small": "configs/sam2.1/sam2.1_hiera_s.yaml",
    "sam2.1_hiera_base_plus": "configs/sam2.1/sam2.1_hiera_b+.yaml",
    "sam2.1_hiera_large": "configs/sam2.1/sam2.1_hiera_l.yaml",
}

model = None  # SAM2ImagePredictor. 로딩 전에는 None이라 /health가 503을 돌려줌
# predictor는 set_image()의 임베딩을 내부에 들고 있어서 요청 두 개가 겹치면 섞임
model_lock = threading.Lock()


def load_model():
    from sam2.build_sam import build_sam2
    from sam2.sam2_image_predictor import SAM2ImagePredictor

    if TORCH_THREADS > 0:
        torch.set_num_threads(TORCH_THREADS)
    sam = build_sam2(CONFIGS[SAM2_MODEL], f"/weights/{SAM2_MODEL}.pt", device=DEVICE,
                     hydra_overrides_extra=[f"++model.image_size={SAM2_IMAGE_SIZE}"])
    predictor = SAM2ImagePredictor(sam)
    # predictor는 특징맵 크기를 1024 입력 기준으로 고정해 두므로 입력 크기에 맞춰 바꿈
    s = SAM2_IMAGE_SIZE
    predictor._bb_feat_sizes = [(s // 4, s // 4), (s // 8, s // 8), (s // 16, s // 16)]
    return predictor


@asynccontextmanager
async def lifespan(app: FastAPI):
    global model
    model = load_model()
    yield


app = FastAPI(lifespan=lifespan)


def judge(mask: np.ndarray, cookie_id: int, line: int) -> Result:
    """마스크 하나 → 원형도·솔리디티 판정. 임계값의 전제인 설계 5장 계산 방식을 그대로 따른다."""
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:  # SAM 2가 아무것도 못 땀: 판정할 수 없으니 불량으로 넘김
        return Result(cookie_id=cookie_id, line=line, polygon=[], area=0, perimeter=0,
                      circularity=0, solidity=0, verdict="NG")

    contour = max(contours, key=cv2.contourArea)  # 초코칩 등으로 생긴 구멍과 잔조각은 무시
    contour = cv2.approxPolyDP(contour, 1.0, True)  # 픽셀 계단만큼 둘레가 길게 재지는 것을 막음
    area = cv2.contourArea(contour)
    perimeter = cv2.arcLength(contour, True)
    hull = cv2.contourArea(cv2.convexHull(contour))

    circularity = 4 * math.pi * area / perimeter**2 if perimeter > 0 else 0.0
    solidity = area / hull if hull > 0 else 0.0
    ok = circularity >= CIRC_THRESHOLD and solidity >= SOLIDITY_THRESHOLD
    return Result(
        cookie_id=cookie_id, line=line,
        polygon=[(float(x), float(y)) for x, y in contour.reshape(-1, 2)],
        area=area, perimeter=perimeter,
        circularity=circularity, solidity=solidity,
        verdict="OK" if ok else "NG",
    )


@app.get("/health")
def health(response: Response):
    if model is None:
        response.status_code = 503
    return {"ok": model is not None}


# async가 아닌 def라서 FastAPI가 스레드에서 돌림. 추론 중에도 /health가 응답해야 healthcheck에 안 걸림
@app.post("/infer", response_model=InferResponse)
def infer(meta: str = Form(...), image: UploadFile = File(...)):
    req = InferRequest.model_validate_json(meta)
    if not req.targets:
        return InferResponse(results=[])

    bgr = cv2.imdecode(np.frombuffer(image.file.read(), np.uint8), cv2.IMREAD_COLOR)
    if bgr is None:
        raise HTTPException(400, "image를 디코드할 수 없음")
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)  # SAM 2는 RGB를 받음
    h, w = rgb.shape[:2]

    # 임베딩은 프레임당 한 번, 박스들은 한 번에 디코딩
    boxes = np.array([t.box for t in req.targets], dtype=np.float32)
    with model_lock, torch.inference_mode():
        model.set_image(rgb)
        masks, _, _ = model.predict(box=boxes, multimask_output=False)
    masks = (masks.reshape(-1, h, w) > 0).astype(np.uint8)  # 박스 1개면 (1,H,W), 여러 개면 (N,1,H,W)

    return InferResponse(results=[judge(m, t.cookie_id, t.line) for m, t in zip(masks, req.targets)])
