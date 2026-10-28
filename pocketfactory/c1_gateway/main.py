# C1 Gateway: 프레임 수신, C2→C3→C4 호출, 대시보드 푸시 (설계 3장)
from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
def health():
    return {"ok": True}
