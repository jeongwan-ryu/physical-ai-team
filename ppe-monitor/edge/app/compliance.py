"""착용 판정 (interface 5.3). 의존성 없는 순수 함수. main.py가 import해서 씁니다."""

VEST_TOP = 0.2
VEST_BOTTOM = 0.7


def _center(box):
    x1, y1, x2, y2 = box
    return (x1 + x2) / 2, (y1 + y2) / 2


def _inside(point, box, top_ratio, bottom_ratio):
    """point가 box의 가로 범위 안, 세로 top_ratio~bottom_ratio 영역 안에 있는지"""
    cx, cy = point
    x1, y1, x2, y2 = box
    h = y2 - y1
    return x1 <= cx <= x2 and y1 + top_ratio * h <= cy <= y1 + bottom_ratio * h


def judge(dets, conf_th, head_ratio):
    """dets: [(name, conf, [x1, y1, x2, y2]), ...]  # name은 모델 클래스 이름 그대로
    반환: interface 5.1의 persons 리스트 [{"bbox", "conf", "helmet", "vest"}, ...]"""
    persons = [(conf, box) for name, conf, box in dets if name == "Person"]
    hats = [_center(box) for name, conf, box in dets if name == "Hardhat" and conf >= conf_th]
    vests = [_center(box) for name, conf, box in dets if name == "Safety Vest" and conf >= conf_th]

    result = []
    for conf, box in persons:
        result.append({
            "bbox": [int(v) for v in box],
            "conf": round(float(conf), 2),
            "helmet": any(_inside(c, box, 0.0, head_ratio) for c in hats),
            "vest": any(_inside(c, box, VEST_TOP, VEST_BOTTOM) for c in vests),
        })
    return result


class Debouncer:
    """위반 상태를 confirm_frames 연속 프레임으로 확정·해제합니다."""

    def __init__(self, confirm_frames):
        self.confirm_frames = confirm_frames
        self.state = False  # 현재 위반 확정 상태
        self.count = 0      # 현재 상태와 반대인 입력이 연속으로 들어온 횟수

    def update(self, violating: bool) -> bool:
        """위반이 새로 확정된 프레임에서만 True를 반환"""
        if violating == self.state:
            self.count = 0
            return False
        self.count += 1
        if self.count < self.confirm_frames:
            return False
        self.state = violating
        self.count = 0
        return self.state
