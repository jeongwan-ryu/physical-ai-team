# C3 SAM 2: 마스크 추출, 원형도·솔리디티 판정 (설계 5장)
from fastapi import FastAPI, Response

app = FastAPI()
model = object()  # TODO: 시작 시 SAM 2 로딩. 로딩 전에는 None이어야 /health가 503을 돌려줌


@app.get("/health")
def health(response: Response):
    if model is None:
        response.status_code = 503
    return {"ok": model is not None}
