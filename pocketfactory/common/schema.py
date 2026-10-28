# 서비스 간 메시지 규격 (설계 7장). 바꿀 때는 PR로 올리고 양쪽 담당자가 확인한다.
#
# 내부 호출은 모두 multipart/form-data, 파트 이름은 meta(JSON 문자열)와 image(JPEG).
#   C1 → C2  POST /process  meta=FrameMeta      image=원본  → 응답 JSON  PreprocessResponse
#   C1 → C3  POST /infer    meta=InferRequest   image=원본  → 응답 JSON  InferResponse
#   C1 → C4  POST /render   meta=RenderRequest  image=원본  → 응답 JPEG  (마킹 이미지)
#
# 좌표는 모두 원본 프레임 픽셀 기준. SAM 2가 크기 조정을 내부에서 하므로 리사이즈·역변환은 없다.
#
# 받는 쪽 예:
#   @app.post("/infer")
#   async def infer(meta: str = Form(...), image: UploadFile = File(...)):
#       req = InferRequest.model_validate_json(meta)
from typing import Literal

from pydantic import BaseModel


class FrameMeta(BaseModel):  # C1이 만듦
    frame_id: int  # 스트림별 일련번호
    stream_id: str  # 폰, 시뮬레이터 등 입력 구분
    ts_recv: float  # C1 수신 시각 (epoch 초). 지연 계산 기준
    ts_capture: float | None = None  # 보낸 쪽 시각, 참고용 (시계가 어긋날 수 있음)


class Target(BaseModel):  # C2가 만듦. 검사선을 막 지난 과자 하나
    cookie_id: int  # 스트림별 일련번호
    line: int  # 컨베이어 라인 번호 (위에서부터 0)
    box: tuple[float, float, float, float]  # x1, y1, x2, y2. SAM 2 박스 프롬프트


class PreprocessResponse(BaseModel):  # C2 → C1
    targets: list[Target]  # 검사 대상이 없으면 빈 목록


class InferRequest(BaseModel):  # C1 → C3
    frame: FrameMeta
    targets: list[Target]


class Result(BaseModel):  # C3가 만듦. 과자 하나의 판정
    cookie_id: int
    line: int
    polygon: list[tuple[float, float]]  # 외곽선 꼭짓점
    area: float
    perimeter: float
    circularity: float
    solidity: float
    verdict: Literal["OK", "NG"]


class InferResponse(BaseModel):  # C3 → C1
    results: list[Result]


class RenderRequest(BaseModel):  # C1 → C4
    frame: FrameMeta
    results: list[Result]
