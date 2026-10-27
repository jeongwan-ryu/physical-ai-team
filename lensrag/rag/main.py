"""질문을 받아 비슷한 지문을 찾고 Gemini로 한국어 답변을 만드는 rag 서버.

실행: uvicorn rag.main:app --host 0.0.0.0 --port 8001
api만 내부 주소 http://rag:8001/search 로 호출한다.
Supabase·임베딩·Gemini 호출이 전부 동기라서 엔드포인트는 일반 def로 둔다 (FastAPI가 스레드풀에서 실행).
"""
import os

from fastapi import FastAPI, HTTPException
from google import genai
from google.genai import types
from pydantic import BaseModel

from shared.embed import embed_query  # import 시점에 임베딩 모델을 한 번만 로딩
from shared.sb import sb

RAG_FAKE = os.environ.get("RAG_FAKE", "") == "1"
GEMINI_MODEL = os.environ.get("GEMINI_MODEL") or "gemini-3.5-flash-lite"
GEMINI_TIMEOUT_MS = 20_000  # api가 rag를 30초 기다리므로 그보다 먼저 끊어야 sources라도 보여줄 수 있음
MATCH_COUNT = 5

NO_PASSAGES_ANSWER = "아직 검색 가능한 지문이 없습니다. 먼저 카드를 촬영해 주세요."
FAKE_ANSWER = "(테스트) 검색은 정상 동작합니다"

PROMPT = """아래 지문들은 영어 카드를 사진으로 찍어 OCR한 결과라서 오탈자가 있을 수 있다.
지문 내용만 근거로 질문에 한국어로 간결하게 답하라.
- 숫자와 고유명사는 지문에 적힌 표기 그대로 쓴다.
- 답의 근거가 된 카드 번호를 [카드 004] 형식으로 표시한다.
- 지문에서 근거를 찾을 수 없으면 "제공된 지문에서 찾을 수 없습니다"라고만 답한다.

[지문]
{passages}

[질문]
{query}"""

gemini = None if RAG_FAKE else genai.Client(
    api_key=os.environ["GEMINI_API_KEY"],
    http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_MS),
)

app = FastAPI()


class SearchRequest(BaseModel):
    query: str


def card_label(card_no: int | None) -> str:
    return f"[카드 {card_no:03d}]" if card_no is not None else "[카드 ?]"


def generate_answer(query: str, sources: list[dict]) -> str:
    passages = "\n\n".join(f"{card_label(s['card_no'])} {s['content']}" for s in sources)
    res = gemini.models.generate_content(
        model=GEMINI_MODEL,
        contents=PROMPT.format(passages=passages, query=query),
    )
    return (res.text or "").strip() or "답변 생성 중 오류가 발생했습니다: 빈 응답"


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/search")
def search(req: SearchRequest):
    query = req.query.strip()
    if not query:
        raise HTTPException(400, "질문이 비어 있습니다.")

    rows = sb.rpc(
        "match_passages", {"query_embedding": embed_query(query), "match_count": MATCH_COUNT}
    ).execute().data
    sources = [
        {"id": r["id"], "card_no": r["card_no"], "content": r["content"], "score": round(r["score"], 2)}
        for r in rows
    ]

    if not sources:
        return {"answer": NO_PASSAGES_ANSWER, "sources": []}
    if RAG_FAKE:
        return {"answer": FAKE_ANSWER, "sources": sources}

    # Gemini가 실패해도 500 대신 검색 결과는 그대로 보여준다
    try:
        answer = generate_answer(query, sources)
    except Exception as e:
        answer = f"답변 생성 중 오류가 발생했습니다: {e}"
    return {"answer": answer, "sources": sources}
