"""OCR 엔진과 전처리·후처리 함수.

외부에서는 preprocess(), run_ocr(), clean_text(), extract_card_no()만 쓰면 된다.
OCR_ENGINE 환경변수로 엔진을 고른다.
  paddle (기본) : PaddleOCR 2.8.1, 영어 모델, CPU
  gemini        : Gemini에 이미지를 보내 텍스트 추출 (Plan B)
  fake          : demo/passages.json 원문을 순서대로 반환 (PaddleOCR 준비 전 연결 테스트용)
"""
import io
import itertools
import json
import os
import re
from pathlib import Path

import pillow_heif
from PIL import Image, ImageOps

pillow_heif.register_heif_opener()  # 아이폰 HEIC 사진도 열 수 있게

OCR_ENGINE = os.getenv("OCR_ENGINE", "paddle").strip().lower()
MAX_SIDE = 1600          # OCR 전 긴 변 최대 크기 (CPU 속도 확보)
MIN_CONFIDENCE = 0.5     # PaddleOCR 결과 중 이보다 낮은 줄은 버림
PASSAGES_PATH = Path(os.getenv("PASSAGES_PATH", Path(__file__).resolve().parents[1] / "demo" / "passages.json"))


# ---------- 전처리 ----------

def preprocess(data: bytes) -> Image.Image:
    """업로드된 바이트 → 회전 보정, RGB, 긴 변 MAX_SIDE로 축소한 PIL 이미지."""
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)
    img = img.convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    return img


# ---------- 후처리 ----------

def clean_text(text: str) -> str:
    """줄마다 공백 정리, 빈 줄 제거."""
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


_CARD_TOKEN = re.compile(r"(?<![0-9A-Za-z])([0-9Oo]{3})(?![0-9A-Za-z])")


def extract_card_no(text: str, head_lines: int = 5) -> int | None:
    """앞쪽 몇 줄에서 001~100 사이 3자리 카드 번호를 찾는다. 'O04'처럼 0을 O로 읽은 경우도 보정."""
    for line in text.splitlines()[:head_lines]:
        for token in _CARD_TOKEN.findall(line):
            if not any(ch.isdigit() for ch in token):
                continue  # "Ooo" 같은 글자만 있는 경우 제외
            value = int(token.replace("O", "0").replace("o", "0"))
            if 1 <= value <= 100:
                return value
    return None


def join_lines(boxes: list[tuple[float, float, float, str]]) -> str:
    """(top, bottom, left, text) 목록을 위→아래, 왼→오른쪽 순서의 줄로 합친다.
    세로 중심이 같은 줄 높이 안에 들어오는 상자들은 한 줄로 본다."""
    rows: list[list[tuple[float, float, float, str]]] = []
    for box in sorted(boxes, key=lambda b: (b[0] + b[1]) / 2):
        center = (box[0] + box[1]) / 2
        if rows:
            last = rows[-1]
            row_center = sum((b[0] + b[1]) / 2 for b in last) / len(last)
            row_height = max(b[1] - b[0] for b in last)
            if abs(center - row_center) < row_height / 2:
                last.append(box)
                continue
        rows.append([box])
    return "\n".join(" ".join(b[3] for b in sorted(row, key=lambda b: b[2])) for row in rows)


# ---------- 엔진 ----------

class PaddleEngine:
    """PaddleOCR 2.8.1 API 기준 (3.x와 호출 방식이 다르므로 버전을 바꾸지 말 것)."""

    def __init__(self):
        from paddleocr import PaddleOCR

        self.ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)

    def __call__(self, img: Image.Image) -> str:
        import numpy as np

        bgr = np.array(img)[:, :, ::-1].copy()  # PaddleOCR은 OpenCV와 같은 BGR 배열을 받음
        result = self.ocr.ocr(bgr, cls=True)
        return paddle_result_to_text(result)


def paddle_result_to_text(result) -> str:
    """PaddleOCR 2.x 결과 [[ [box, (text, conf)], ... ]] → 줄 텍스트."""
    boxes = []
    for page in result or []:
        for item in page or []:  # 글자가 하나도 없으면 page가 None
            points, (text, conf) = item
            if conf < MIN_CONFIDENCE or not text.strip():
                continue
            ys = [p[1] for p in points]
            xs = [p[0] for p in points]
            boxes.append((min(ys), max(ys), min(xs), text))
    return join_lines(boxes)


class GeminiEngine:
    PROMPT = (
        "This is a phone photo of a computer monitor showing an English text card. "
        "Transcribe all visible text exactly, top to bottom, keeping the line breaks. "
        "Include the 3-digit card number if visible. Output only the text, no explanations."
    )

    def __init__(self):
        from google import genai

        self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self.model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    def __call__(self, img: Image.Image) -> str:
        from google.genai import types

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        response = self.client.models.generate_content(
            model=self.model,
            contents=[types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg"), self.PROMPT],
        )
        return response.text or ""


class FakeEngine:
    """사진은 실제로 받되, OCR 대신 정답 원문을 순서대로 돌려준다."""

    def __init__(self):
        passages = json.loads(PASSAGES_PATH.read_text(encoding="utf-8"))
        self._cycle = itertools.cycle(passages)

    def __call__(self, img: Image.Image) -> str:
        p = next(self._cycle)
        return f"{p['card_no']:03d}\n{p['title']}\n{p['body']}"


_ENGINES = {"paddle": PaddleEngine, "gemini": GeminiEngine, "fake": FakeEngine}
_engine = None


def get_engine():
    global _engine
    if _engine is None:
        if OCR_ENGINE not in _ENGINES:
            raise ValueError(f"OCR_ENGINE은 {list(_ENGINES)} 중 하나여야 합니다: {OCR_ENGINE!r}")
        _engine = _ENGINES[OCR_ENGINE]()
    return _engine


def run_ocr(img: Image.Image) -> str:
    return get_engine()(img)
