"""DB 없이 사진 한 장(또는 폴더)의 전처리 + OCR + 카드 번호 추출만 확인한다.

사용 예:
  python -m worker.test_local 사진.jpg
  python -m worker.test_local 사진폴더/
  OCR_ENGINE=gemini python -m worker.test_local 사진.jpg

카드 번호를 읽으면 demo/passages.json 원문과 비교해 유사도(0~100%)도 출력한다.
"""
import difflib
import json
import sys
import time
from pathlib import Path

from worker.ocr_engine import OCR_ENGINE, PASSAGES_PATH, clean_text, extract_card_no, get_engine, preprocess, run_ocr

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}


def load_answers() -> dict[int, str]:
    if not PASSAGES_PATH.exists():
        return {}
    return {p["card_no"]: f"{p['title']} {p['body']}" for p in json.loads(PASSAGES_PATH.read_text(encoding="utf-8"))}


def similarity(ocr_text: str, answer: str) -> float:
    a = " ".join(ocr_text.split()).lower()
    b = " ".join(answer.split()).lower()
    # autojunk=False: 기본값(True)이면 200자 넘는 글에서 공백·e 같은 흔한 글자를 무시해
    # 거의 똑같은 글도 22%처럼 엉뚱하게 낮은 점수가 나온다
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() * 100


def check(path: Path, answers: dict[int, str]) -> float | None:
    started = time.time()
    img = preprocess(path.read_bytes())
    text = clean_text(run_ocr(img))
    elapsed = time.time() - started
    card_no = extract_card_no(text)

    print(f"\n=== {path.name}  ({img.width}x{img.height}, {elapsed:.1f}s, {len(text)}자) ===")
    print(text)
    print(f"--- 카드 번호: {card_no if card_no is not None else '못 읽음'}")

    if card_no in answers:
        body_only = "\n".join(text.splitlines()[1:])  # 첫 줄(카드 번호) 제외
        score = similarity(body_only, answers[card_no])
        print(f"--- 원문 대비 유사도: {score:.1f}%")
        return score
    return None


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    target = Path(sys.argv[1])
    paths = sorted(p for p in target.iterdir() if p.suffix.lower() in IMAGE_EXTS) if target.is_dir() else [target]
    if not paths:
        print("이미지 파일이 없습니다.")
        sys.exit(1)

    print(f"OCR 엔진: {OCR_ENGINE} (로딩 중...)")
    get_engine()
    answers = load_answers()
    scores = [s for s in (check(p, answers) for p in paths) if s is not None]
    if len(paths) > 1:
        avg = f"{sum(scores) / len(scores):.1f}%" if scores else "-"
        print(f"\n총 {len(paths)}장, 카드 번호 인식 {len(scores)}장, 평균 유사도 {avg}")


if __name__ == "__main__":
    main()
