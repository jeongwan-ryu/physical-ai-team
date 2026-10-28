# 서비스 간 메시지 규격 초안 (설계 7장). 3명이 함께 확정한 뒤 각자 구현을 시작한다.
from typing import Literal

from pydantic import BaseModel


class FrameMeta(BaseModel):  # C1이 만듦
    frame_id: int
    stream_id: str
    ts_capture: float  # 폰 시각, 참고용
    ts_recv: float  # C1 수신 시각, 지연 계산 기준


class Transform(BaseModel):  # C2가 만듦
    scale: float
    offset_x: float
    offset_y: float


class Target(BaseModel):  # C2가 만듦, SAM 2 박스 프롬프트
    cookie_id: int
    line: int
    box: tuple[float, float, float, float]  # x1, y1, x2, y2


class Result(BaseModel):  # C3가 만듦
    cookie_id: int
    polygon: list[tuple[float, float]]
    area: float
    perimeter: float
    circularity: float
    solidity: float
    verdict: Literal["OK", "NG"]
