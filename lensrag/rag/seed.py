"""worker 없이 검색을 먼저 테스트하기 위해 passages.json 원문을 바로 넣는 스크립트.

python -m rag.seed --limit 20   # 앞 20개를 임베딩해서 status='done'으로 insert
python -m rag.seed --clear      # filename='seed'인 row만 삭제
"""
import argparse
import json
from pathlib import Path

from shared.sb import sb

PASSAGES_JSON = Path(__file__).resolve().parent.parent / "demo" / "passages.json"


def clear():
    res = sb.table("passages").delete().eq("filename", "seed").execute()
    print(f"seed row {len(res.data)}개 삭제")


def seed(limit: int):
    from shared.embed import embed_passage  # --clear만 할 때는 모델을 로딩하지 않음

    passages = json.loads(PASSAGES_JSON.read_text(encoding="utf-8"))[:limit]
    for p in passages:
        content = p["title"] + " " + p["body"]
        sb.table("passages").insert({
            "card_no": p["card_no"],
            "filename": "seed",
            "status": "done",
            "content": content,
            "embedding": embed_passage(content),
        }).execute()
        print(f"[카드 {p['card_no']:03d}] {p['title']}")
    print(f"{len(passages)}개 insert 완료")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--clear", action="store_true")
    args = parser.parse_args()

    if args.clear:
        clear()
    else:
        seed(args.limit)
