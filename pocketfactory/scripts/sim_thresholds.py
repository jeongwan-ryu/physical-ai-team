# web/simulator.html의 makeShape를 그대로 옮겨, 이상적인 마스크에서 원형도·솔리디티 분포와 검출률을 계산한다.
# 임계값(c3_sam2/metrics.py)의 근거. 시뮬레이터 형상이나 EPS를 바꾸면 다시 돌린다.
# 실행: python3 -m scripts.sim_thresholds  (pocketfactory 폴더에서, numpy·opencv 필요)
import cv2
import numpy as np

from c3_sam2.metrics import shape_metrics, verdict

SEG = 180
TYPES = ["bite", "cut", "wedge", "half"]
rng = np.random.default_rng(0)


def make_rad(kind, strength):
    k = strength / 100 * (0.55 + rng.random() * 0.45)
    d0 = rng.random() * 2 * np.pi
    bite_r = 0.35 + k * 0.55
    bite_d = 1 + bite_r * (0.62 - k * 0.34)
    a = np.arange(SEG) / SEG * 2 * np.pi
    d = ((a - d0 + np.pi * 3) % (np.pi * 2)) - np.pi
    c = np.cos(d)
    r = np.ones(SEG)
    if kind == "bite":
        b = bite_d * c
        disc = b * b - (bite_d ** 2 - bite_r ** 2)
        t = b - np.sqrt(np.clip(disc, 0, None))
        m = (disc > 0) & (t > 0) & (t < 1)
        r[m] = t[m]
    elif kind in ("cut", "half"):
        D = 0.86 - k * 0.52 if kind == "cut" else 0.17 - k * 0.15
        m = c > 0.001
        r[m] = np.minimum(1, D / c[m])
    elif kind == "wedge":
        w = 0.22 + k * 0.5
        m = np.abs(d) < w
        r[m] = 0.07 + np.abs(d[m]) / w * 0.1
    return np.maximum(0.06, r)


def mask_of(rad, R):
    size = int(R * 2 + 20)
    cx, cy = size / 2 + rng.random(), size / 2 + rng.random()
    if rad is None:  # 정상품은 진짜 원
        a, rr = np.linspace(0, 2 * np.pi, 720, endpoint=False), np.full(720, float(R))
    else:
        a, rr = np.arange(SEG) / SEG * 2 * np.pi + rng.random() * 2 * np.pi, R * rad
    pts = np.stack([cx + np.cos(a) * rr, cy + np.sin(a) * rr], 1)
    m = np.zeros((size, size), np.uint8)
    cv2.fillPoly(m, [np.round(pts * 16).astype(np.int32)], 1, shift=4)
    return m


def ng_rate(kind, strength, R, n):
    ms = [shape_metrics(mask_of(None if kind == "round" else make_rad(kind, strength), R)) for _ in range(n)]
    return np.mean([verdict(m[3], m[4]) == "NG" for m in ms]), np.array([m[3:] for m in ms])


if __name__ == "__main__":
    for R in [20, 39, 78]:  # 과자 지름 40 / 78(기본) / 156 px
        fp, rv = ng_rate("round", 0, R, 500)
        print(f"R={R}: 정상 원형도 {rv[:, 0].min():.3f}~{rv[:, 0].max():.3f}, 정상→NG 오판 {fp * 100:.1f}%")
        for k in TYPES:
            _, v = ng_rate(k, 55, R, 300)
            print(f"  {k:5} (결손 55%) 원형도 ≤{v[:, 0].max():.3f}  솔리디티 ≤{v[:, 1].max():.3f}")
        rates = [f"{s}%→{np.mean([ng_rate(k, s, R, 200)[0] for k in TYPES]) * 100:.1f}" for s in [10, 20, 30, 40, 55]]
        print("  결손 크기별 검출률:", " ".join(rates))
