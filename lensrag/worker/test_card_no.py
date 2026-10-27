"""extract_card_no 확인용. 실행: python -m worker.test_card_no

첫 줄 값들은 컨베이어 카드 캡처 100장을 PaddleOCR로 읽었을 때 실제로 나온 것이다.
"""
from worker.ocr_engine import extract_card_no

CASES = [
    ("010\nWEATHER LOG", 10),
    ("0 0 4\nQUARTERLY OPERATIONS SUMMARY\nDefect density fell to O.032", 4),  # 띄어 읽음, 본문 숫자 무시
    ("0 01\nTHE QUIET MACHINERY", 1),
    ("07 5\nTHE ALLOTMENT", 75),
    ("602\n...", 2),     # 흐린 앞자리 0을 6으로 읽음
    ("6 62\n...", 62),
    ("O04\n...", 4),     # 0을 O로 읽음
    ("100\n...", 100),
    ("THE REPAIR SHOP\nunit shuts off at 100 C", None),  # 번호를 못 읽었으면 본문 숫자를 쓰지 않음
    ("101\n...", None),
    ("003 004\n...", None),  # 카드 두 장이 한 줄로 합쳐진 경우
    ("", None),
]

for text, expected in CASES:
    got = extract_card_no(text)
    assert got == expected, f"{text.splitlines()[:1]} -> {got}, 기대값 {expected}"
print(f"extract_card_no: {len(CASES)}개 모두 통과")
