# C2 Preprocess: 조명 보정, 과자 검출, 검사선 통과 선별 (설계 4장)
from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
def health():
    return {"ok": True}
