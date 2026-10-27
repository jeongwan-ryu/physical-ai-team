# worker 컨테이너 (B 담당)

`uploaded` 상태 사진을 가져와 OCR → 카드 번호·중복 처리 → 임베딩 → `done`으로 저장합니다.

## 파일

| 파일 | 내용 |
|---|---|
| `Dockerfile` | python 3.11-slim, CPU 전용 torch, OpenCV·Paddle 시스템 라이브러리 |
| `requirements.txt` | 버전 고정 (PaddleOCR 2.8.1 + paddlepaddle 2.6.2 + numpy 1.26.4) |
| `ocr_engine.py` | 전처리, OCR 엔진 3종(paddle / gemini / fake), 카드 번호 추출 |
| `worker.py` | 메인 루프 (1초 polling) |
| `test_local.py` | DB 없이 사진만으로 OCR 결과·원문 대비 유사도 확인 |
| `test_card_no.py` | 카드 번호 추출 규칙 확인 (`python -m worker.test_card_no`) |

함께 들어 있는 `shared/`(sb.py, embed.py)와 `demo/`(컨베이어 페이지, passages.json)는 리드가 공유하는 것과 같은 내용입니다. 프로젝트 루트에 그대로 두면 됩니다.

## 버전을 이렇게 고정한 이유

- PaddleOCR 3.x는 호출 방식과 결과 형식이 2.x와 완전히 달라서, 인터넷 예제와 섞이면 바로 깨집니다. 결과 형식이 잘 알려진 2.8.1로 고정했습니다. **버전을 올리지 마세요.**
- paddlepaddle 2.6.x는 numpy 2를 지원하지 않아 `numpy==1.26.4`로 고정했고, numpy 2를 요구하는 최신 OpenCV가 끌려오지 않도록 OpenCV도 고정했습니다.
- Python 3.12 이상에서는 `setuptools`가 없으면 paddle import가 실패해서 requirements에 넣어두었습니다.
- torch는 Dockerfile에서 CPU 전용으로 먼저 설치합니다 (CUDA 버전은 수 GB).

## compose 설정 (리드의 docker-compose.yml에 이미 있음)

```yaml
worker:
  build: { context: ., dockerfile: worker/Dockerfile }
  env_file: .env
  restart: unless-stopped
  volumes:
    - ./models/hf:/root/.cache
    - ./models/paddleocr:/root/.paddleocr
    - ./models/paddlex:/root/.paddlex
```

`.env`에 `OCR_ENGINE=paddle`(기본) / `gemini` / `fake` 중 하나를 넣어 엔진을 바꿉니다. `gemini`를 쓰면 `GEMINI_API_KEY`, `GEMINI_MODEL`도 필요합니다.

## 테스트 순서

**1. 빌드** (처음엔 10분 이상 걸릴 수 있음, 전날 해두기)
```bash
docker compose build worker
```

**2. fake 모드로 DB 연결 확인** — PaddleOCR 없이 실제 원문으로 흐름 확인
```bash
# .env에 OCR_ENGINE=fake
docker compose up worker
```
A의 페이지로 사진을 올리면 로그에 `id=1 card=001 chars=... -> done`이 찍히고 Supabase 테이블에서 `done`, `content`, `embedding`이 채워졌는지 확인합니다.

**3. 실제 사진으로 OCR만 확인** — 폰으로 컨베이어 페이지를 찍은 사진을 `samples/` 폴더에 넣고
```bash
docker compose run --rm -e OCR_ENGINE=paddle -v ./samples:/app/samples worker python -m worker.test_local /app/samples
```
사진별 OCR 결과, 카드 번호, 원문 대비 유사도, 평균이 출력됩니다. 처음 실행 때 PaddleOCR 모델을 내려받습니다 (`models/paddleocr`에 저장되어 다음부터는 바로 시작).

**4. 실제 모드로 전체 루프**
```bash
# .env에 OCR_ENGINE=paddle
docker compose up worker
```

## 인식이 잘 안 될 때

- `test_local` 유사도가 낮으면 먼저 촬영 조건을 바꿉니다: 컨베이어 페이지 글자 크기·카드 높이 키우기, 모니터 밝기 올리기, 정면에서 반사광 없이, 카드 한 장이 화면을 꽉 채우게.
- 카드 번호는 OCR 결과의 **첫 줄**에서만 찾습니다 (본문 숫자를 번호로 착각하지 않도록). 자주 못 읽으면 사진 위쪽에 카드 번호 말고 다른 글자가 찍히지 않았는지 확인하고, 카드 한 장만 화면에 들어오게 찍습니다.
- 잡음 줄이 많이 섞이면 `MIN_CONFIDENCE`(기본 0.5)를 0.7 정도로 올립니다.
- 큰 글자가 뭉개지면 `MAX_SIDE`(기본 1600)를 2000으로 올립니다 (대신 느려짐).

## Plan B: 12시까지 PaddleOCR이 안 되면

`.env`에서 `OCR_ENGINE=gemini`로 바꾸고 다시 띄웁니다. 코드 수정은 필요 없습니다. 빌드 자체가 실패하는 경우엔 `requirements.txt`에서 `paddlepaddle`, `paddleocr`, `opencv-*` 네 줄을 지우고 다시 빌드하면 됩니다.

## 검증 범위

- 확인 완료: 의존성 버전 조합 충돌 없음, PaddleOCR 2.8.1 설치·import, 카드 번호 추출(`O04` 같은 오인식 보정 포함), 줄 정렬, 큰 사진 축소·EXIF 회전·HEIC 열기, fake 엔진, 가짜 DB로 worker 전체 흐름(정상 / 같은 카드 재촬영 / 더 잘 찍힌 재촬영 / 글자 부족 / 번호 없음 / 다운로드 실패 / 재시작 시 processing 복구).
- 직접 확인 필요: Docker 빌드, PaddleOCR 실제 추론(모델 서버 `paddleocr.bj.bcebos.com`과 `huggingface.co` 접속이 필요하므로 작업 장소 네트워크에서 미리 확인), 실제 Supabase 연결, Gemini 모델명.
