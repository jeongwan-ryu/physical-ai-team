# C4 Visualizer: 원본 마킹, 판정 이력 저장 (설계 6장)
from fastapi import FastAPI, File, Form, Response, UploadFile

from common.schema import RenderRequest

app = FastAPI()


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/render")
async def render(meta: str = Form(...), image: UploadFile = File(...)):
    req = RenderRequest.model_validate_json(meta)
    # TODO: 마킹, SQLite 기록, 불량 이미지 저장 (임시: 원본을 그대로 돌려줌)
    return Response(await image.read(), media_type="image/jpeg")
