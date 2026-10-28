# C3 SAM 2: 마스크 추출, 원형도·솔리디티 판정 (설계 5장)
from fastapi import FastAPI, File, Form, Response, UploadFile

from common.schema import InferRequest, InferResponse, Result

app = FastAPI()
model = object()  # TODO: 시작 시 SAM 2 로딩. 로딩 전에는 None이어야 /health가 503을 돌려줌


@app.get("/health")
def health(response: Response):
    if model is None:
        response.status_code = 503
    return {"ok": model is not None}


@app.post("/infer", response_model=InferResponse)
async def infer(meta: str = Form(...), image: UploadFile = File(...)):
    req = InferRequest.model_validate_json(meta)
    # TODO: SAM 2 마스크 → 원형도·솔리디티 판정 (임시: 박스를 외곽선으로 보고 전부 OK)
    results = []
    for t in req.targets:
        x1, y1, x2, y2 = t.box
        w, h = x2 - x1, y2 - y1
        results.append(Result(
            cookie_id=t.cookie_id, line=t.line,
            polygon=[(x1, y1), (x2, y1), (x2, y2), (x1, y2)],
            area=w * h, perimeter=2 * (w + h),
            circularity=1.0, solidity=1.0, verdict="OK",
        ))
    return InferResponse(results=results)
