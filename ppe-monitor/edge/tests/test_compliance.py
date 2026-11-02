"""compliance.py 테스트. 실행: cd edge && docker compose run --rm edge python tests/test_compliance.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))  # 컨테이너 밖에서도 실행 가능

from compliance import Debouncer, judge

CONF_TH = 0.4
HEAD_RATIO = 0.3

PERSON = ("Person", 0.9, [100.4, 0.0, 200.6, 400.0])  # 머리 영역 y 0~120, 조끼 영역 y 80~280
HAT = ("Hardhat", 0.8, [130, 10, 170, 50])             # 중심 (150, 30)
VEST = ("Safety Vest", 0.8, [120, 150, 180, 250])      # 중심 (150, 200)


def test_wearing():
    persons = judge([PERSON, HAT, VEST, ("NO-Mask", 0.9, [0, 0, 10, 10])], CONF_TH, HEAD_RATIO)
    assert persons == [{"bbox": [100, 0, 200, 400], "conf": 0.9, "helmet": True, "vest": True}], persons
    assert all(isinstance(v, int) for v in persons[0]["bbox"])


def test_no_helmet():
    p = judge([PERSON, VEST], CONF_TH, HEAD_RATIO)[0]
    assert p["helmet"] is False and p["vest"] is True
    # 안전모가 머리 영역 밖(배 높이)에 있으면 미착용
    low_hat = ("Hardhat", 0.8, [130, 180, 170, 220])
    p = judge([PERSON, low_hat, VEST], CONF_TH, HEAD_RATIO)[0]
    assert p["helmet"] is False


def test_no_vest():
    p = judge([PERSON, HAT], CONF_TH, HEAD_RATIO)[0]
    assert p["helmet"] is True and p["vest"] is False
    # 다른 사람 옆(가로 범위 밖)에 있는 조끼는 인정하지 않음
    far_vest = ("Safety Vest", 0.8, [300, 150, 360, 250])
    p = judge([PERSON, HAT, far_vest], CONF_TH, HEAD_RATIO)[0]
    assert p["vest"] is False


def test_no_person():
    assert judge([], CONF_TH, HEAD_RATIO) == []
    assert judge([HAT, VEST], CONF_TH, HEAD_RATIO) == []


def test_low_conf():
    weak_hat = ("Hardhat", 0.3, [130, 10, 170, 50])
    weak_vest = ("Safety Vest", 0.3, [120, 150, 180, 250])
    p = judge([PERSON, weak_hat, weak_vest], CONF_TH, HEAD_RATIO)[0]
    assert p["helmet"] is False and p["vest"] is False


def test_two_persons():
    other = ("Person", 0.7, [300, 0, 400, 400])
    persons = judge([PERSON, HAT, VEST, other], CONF_TH, HEAD_RATIO)
    assert [(p["helmet"], p["vest"]) for p in persons] == [(True, True), (False, False)]


def test_debouncer():
    d = Debouncer(3)
    # 확정: 3번 연속 위반인 세 번째 프레임에서만 True
    assert [d.update(True) for _ in range(3)] == [False, False, True]
    # 유지: 위반이 이어져도 다시 True가 나오지 않음
    assert [d.update(True) for _ in range(5)] == [False] * 5
    # 깜빡임 무시: 정상 1~2프레임은 해제되지 않음
    assert [d.update(v) for v in (False, False, True)] == [False, False, False]
    assert d.state is True
    # 해제: 정상 3프레임 연속이면 해제 (반환은 False)
    assert [d.update(False) for _ in range(3)] == [False, False, False]
    assert d.state is False
    # 위반 깜빡임도 무시
    assert [d.update(v) for v in (True, True, False)] == [False] * 3
    assert d.state is False
    # 재확정
    assert [d.update(True) for _ in range(3)] == [False, False, True]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    print("all passed")
