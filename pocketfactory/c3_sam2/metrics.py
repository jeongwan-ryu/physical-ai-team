# 마스크 → 원형도·솔리디티 → OK/NG (설계 5장).
# 임계값은 시뮬레이터 형상으로 계산해 정했다 (scripts/sim_thresholds.py). EPS를 바꾸면 임계값도 다시 계산한다.
import os

import cv2
import numpy as np

EPS = 1.0  # approxPolyDP 허용 오차(px). 픽셀 계단 때문에 둘레가 부풀려지는 것을 막음
CIRC_THRESHOLD = float(os.environ.get("CIRC_THRESHOLD") or 0.96)
SOLIDITY_THRESHOLD = float(os.environ.get("SOLIDITY_THRESHOLD") or 0.985)


def shape_metrics(mask):
    """과자 하나의 이진 마스크 → (polygon, area, perimeter, circularity, solidity)"""
    cs, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    c = cv2.approxPolyDP(max(cs, key=cv2.contourArea), EPS, True)
    area = cv2.contourArea(c)
    per = cv2.arcLength(c, True)
    hull = cv2.contourArea(cv2.convexHull(c))
    return c.reshape(-1, 2), area, per, 4 * np.pi * area / per ** 2, area / hull


def verdict(circularity, solidity):
    return "NG" if circularity < CIRC_THRESHOLD or solidity < SOLIDITY_THRESHOLD else "OK"


if __name__ == "__main__":
    # python -m c3_sam2.metrics  (pocketfactory 폴더에서)
    def judge(m):
        return verdict(*shape_metrics(m)[3:])

    circle = cv2.circle(np.zeros((100, 100), np.uint8), (50, 50), 39, 1, -1)
    half = circle.copy()
    half[:, 50:] = 0
    bite = circle.copy()
    cv2.circle(bite, (89, 50), 15, 0, -1)
    assert judge(circle) == "OK", shape_metrics(circle)[3:]
    assert judge(half) == "NG", shape_metrics(half)[3:]
    assert judge(bite) == "NG", shape_metrics(bite)[3:]
    print("ok")
