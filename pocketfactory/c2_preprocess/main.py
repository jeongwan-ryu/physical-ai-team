# C2 Preprocess: 조명 보정, 과자 검출, 검사선 통과 선별 (설계 4장)
from fastapi import FastAPI, File, Form, UploadFile

from common.schema import FrameMeta, PreprocessResponse

app = FastAPI()


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/process", response_model=PreprocessResponse)
async def process(meta: str = Form(...), image: UploadFile = File(...)):
    frame = FrameMeta.model_validate_json(meta)
    return PreprocessResponse(targets=[])  # TODO: 검출과 검사선 통과 추적 (임시: 항상 대상 없음)
