"""demo/ocr-conveyor-test.html의 PASSAGES 배열을 demo/passages.json으로 추출한다.
컨베이어 페이지의 지문을 바꿨을 때만 다시 실행: python scripts/extract_passages.py
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
html = (ROOT / "demo" / "ocr-conveyor-test.html").read_text(encoding="utf-8")
start = html.index("const PASSAGES = [") + len("const PASSAGES = ")
end = html.index("];", start) + 1
js = html[start:end]
js = re.sub(r"(?m)^(\s*\{?\s*)title:", r'\1"title":', js)
js = re.sub(r"\bbody:", '"body":', js)
js = re.sub(r",(\s*[\]\}])", r"\1", js)
passages = [{"card_no": i + 1, "title": p["title"], "body": " ".join(p["body"])} for i, p in enumerate(json.loads(js))]
(ROOT / "demo" / "passages.json").write_text(json.dumps(passages, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"{len(passages)}개 지문 저장 완료")
