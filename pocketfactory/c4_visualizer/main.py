# C4 Visualizer: 원본 마킹, 판정 이력 저장 (설계 6장)
from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
def health():
    return {"ok": True}
