"""uploaded 상태 사진을 가져와 OCR → 카드 번호·중복 처리 → 임베딩 → 저장하는 worker.

실행: python -m worker.worker
worker는 1개만 띄운다고 가정한다.
"""
import logging
import time

from worker.ocr_engine import OCR_ENGINE, clean_text, extract_card_no, get_engine, preprocess, run_ocr

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("worker")
log.setLevel(logging.INFO)  # PaddleOCR이 root 로거를 WARNING으로 바꿔도 진행 로그가 보이게

POLL_SECONDS = 1.0
MIN_CHARS = 20  # 이보다 짧으면 "거의 못 읽음"으로 처리

# Supabase 클라이언트와 임베딩 모델은 시작할 때 한 번만 로딩
log.info("Supabase 연결, 임베딩 모델 로딩 중...")
from shared.sb import sb  # noqa: E402
from shared.embed import embed_passage  # noqa: E402

TABLE = "passages"
BUCKET = "uploads"


def reset_stuck_rows() -> None:
    """이전에 worker가 죽으면서 processing으로 남은 row를 다시 대기 상태로."""
    res = sb.table(TABLE).update({"status": "uploaded"}).eq("status", "processing").execute()
    if res.data:
        log.info("processing에 멈춰 있던 %d건을 uploaded로 되돌림", len(res.data))


def claim_next() -> dict | None:
    """가장 오래된 uploaded 1건을 processing으로 바꾸고 반환. 없으면 None."""
    res = (
        sb.table(TABLE).select("id, image_path")
        .eq("status", "uploaded").order("created_at").limit(1).execute()
    )
    if not res.data:
        return None
    row = res.data[0]
    claimed = (
        sb.table(TABLE).update({"status": "processing", "error": None})
        .eq("id", row["id"]).eq("status", "uploaded").execute()
    )
    return row if claimed.data else None


def mark_failed(row_id: int, message: str) -> None:
    sb.table(TABLE).update({"status": "failed", "error": message[:500]}).eq("id", row_id).execute()


def find_existing_done(card_no: int, exclude_id: int) -> dict | None:
    res = (
        sb.table(TABLE).select("id, content")
        .eq("card_no", card_no).eq("status", "done").neq("id", exclude_id)
        .limit(1).execute()
    )
    return res.data[0] if res.data else None


def process(row: dict) -> tuple[str, int | None, int]:
    """row 하나 처리. (최종 상태, 카드 번호, 글자 수)를 반환."""
    row_id = row["id"]
    data = sb.storage.from_(BUCKET).download(row["image_path"])
    img = preprocess(data)
    text = clean_text(run_ocr(img))

    if len(text) < MIN_CHARS:
        mark_failed(row_id, f"텍스트를 거의 읽지 못함 ({len(text)}자)")
        return "failed", None, len(text)

    card_no = extract_card_no(text)
    existing = find_existing_done(card_no, row_id) if card_no is not None else None

    if existing and len(text) <= len(existing.get("content") or ""):
        # 이미 더 잘 읽힌 같은 카드가 있음 → 이번 것은 검색에서 제외
        sb.table(TABLE).update({"status": "duplicate", "content": text, "card_no": card_no}).eq("id", row_id).execute()
        return "duplicate", card_no, len(text)

    # 이번 것을 done으로. 임베딩을 먼저 만들어서, 실패해도 기존 done이 사라지지 않게 한다.
    embedding = embed_passage(text)
    sb.table(TABLE).update(
        {"status": "done", "content": text, "card_no": card_no, "embedding": embedding, "error": None}
    ).eq("id", row_id).execute()
    if existing:
        sb.table(TABLE).update({"status": "duplicate"}).eq("id", existing["id"]).execute()
    return "done", card_no, len(text)


def main() -> None:
    log.info("OCR 엔진: %s (로딩 중...)", OCR_ENGINE)
    get_engine()  # 첫 사진 처리 때가 아니라 시작할 때 모델을 미리 로딩
    reset_stuck_rows()
    log.info("준비 완료. uploaded 사진을 기다립니다.")

    while True:
        try:
            row = claim_next()
        except Exception as e:  # 네트워크 일시 오류 등
            log.warning("조회 실패: %s", e)
            time.sleep(3)
            continue

        if row is None:
            time.sleep(POLL_SECONDS)
            continue

        started = time.time()
        try:
            status, card_no, length = process(row)
        except Exception as e:
            log.exception("id=%s 처리 실패", row["id"])
            try:
                mark_failed(row["id"], f"{type(e).__name__}: {e}")
            except Exception:
                log.exception("failed 상태 기록도 실패")
            status, card_no, length = "failed", None, 0

        card = f"{card_no:03d}" if card_no is not None else "---"
        log.info("id=%s card=%s chars=%d %.1fs -> %s", row["id"], card, length, time.time() - started, status)


if __name__ == "__main__":
    main()
