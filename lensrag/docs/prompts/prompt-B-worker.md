# [B] worker 컨테이너 생성 프롬프트

아래 전체를 복사해서 LLM에 그대로 붙여넣으세요.

---

너는 Python으로 OCR 파이프라인과 Docker 이미지를 만드는 데 능숙한 개발자야. 아래 공통 컨텍스트를 지키면서 `worker` 컨테이너를 완성해줘. 나는 B 담당이고, `api`와 `rag`는 다른 팀원이 만들고 있어.

## 프로젝트 공통 컨텍스트 (변경 금지)

### 프로젝트 개요
하루짜리 3인 팀 프로젝트. PC 대시보드의 QR을 스마트폰으로 찍어 연동한 뒤, 폰 카메라로 PC 모니터에 띄운 "OCR Conveyor Bench" 페이지(영어 지문 카드 100장이 번호 001~100과 함께 흘러가는 페이지)를 촬영한다. 촬영한 사진을 OCR로 추출해 저장하고, 질문하면 관련 지문을 벡터 검색해 Gemini가 한국어로 답한다.

컨테이너는 3개이고 데이터는 전부 Supabase(클라우드 Postgres + pgvector + Storage)에 있다. 공유 볼륨으로 데이터를 주고받지 않는다.
- `api` (A 담당, 포트 8000, 외부 공개): PC 대시보드, QR 연동, 모바일 촬영 페이지, 업로드, 검색 중계
- `worker` (B 담당, 포트 없음): `uploaded` 상태 사진을 가져와 OCR → 카드 번호 추출·중복 처리 → 임베딩 → 저장
- `rag` (C 담당, 포트 8001, 내부 전용): 질문 임베딩 → `match_passages` 벡터 검색 → Gemini 답변
- 컨테이너끼리 직접 통신하는 것은 `api` → `rag` HTTP 호출 하나뿐이다. `api`와 `worker`는 DB의 status 값으로만 협업한다.

### 폴더 구조
```
project/
├── docker-compose.yml
├── .env
├── models/{hf,paddleocr,paddlex}/
├── shared/
│   ├── sb.py          # Supabase 클라이언트 (셋 다 사용)
│   └── embed.py       # 임베딩 함수 (worker, rag만 사용)
├── demo/
│   ├── ocr-conveyor-test.html
│   ├── passages.json  # [{"card_no": 1, "title": "...", "body": "단락들을 공백으로 이은 본문"}, ...]
│   └── questions.json
├── api/      Dockerfile, requirements.txt, main.py, static/dashboard.html, static/mobile.html
├── worker/   Dockerfile, requirements.txt, worker.py
└── rag/      Dockerfile, requirements.txt, main.py
```
- 모든 Dockerfile은 build context가 프로젝트 루트(`.`)이고, `COPY shared/ /app/shared/` 후 `/app`을 작업 디렉터리로 쓴다. import는 `from shared.sb import sb` 형태.
- Python 3.11 기반 slim 이미지.

### Supabase 스키마 (이미 생성되어 있음)
```sql
create table sessions (
  id text primary key,
  connected boolean default false,
  created_at timestamptz default now()
);

create table passages (
  id bigint generated always as identity primary key,
  session_id text references sessions(id),
  card_no int,
  filename text,
  image_path text,                -- Storage 버킷 uploads 안의 경로 ({uuid}.jpg)
  status text default 'uploaded', -- uploaded | processing | done | duplicate | failed
  content text,
  embedding vector(384),
  error text,
  created_at timestamptz default now()
);

create or replace function match_passages(query_embedding vector(384), match_count int)
returns table (id bigint, card_no int, content text, score float)
language sql stable as $$
  select id, card_no, content, 1 - (embedding <=> query_embedding) as score
  from passages where status = 'done'
  order by embedding <=> query_embedding limit match_count;
$$;
```
- Storage 버킷: `uploads` (private)

### 상태 값
| 값 | 누가 바꿈 | 의미 |
|---|---|---|
| uploaded | api | 업로드 완료, 처리 대기 |
| processing | worker | 처리 중 |
| done | worker | 검색 가능 |
| duplicate | worker | 같은 card_no가 이미 done (검색 제외) |
| failed | worker | 실패, error에 이유 |

### 환경변수 (.env, 모든 컨테이너에 env_file로 주입)
```
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_SERVICE_KEY=eyJ...      # 서버 전용. HTML/JS에 절대 노출 금지
GEMINI_API_KEY=...
PUBLIC_BASE_URL=http://192.168.0.10:8000   # QR에 들어갈 PC의 LAN 주소
```
- api 컨테이너에는 추가로 `RAG_URL=http://rag:8001`

### 공통 모듈 (이미 존재, 그대로 사용)
```python
# shared/sb.py
import os
from supabase import create_client
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
```
```python
# shared/embed.py
from sentence_transformers import SentenceTransformer
model = SentenceTransformer("intfloat/multilingual-e5-small")
def embed_passage(text: str) -> list[float]:
    return model.encode("passage: " + text, normalize_embeddings=True).tolist()
def embed_query(text: str) -> list[float]:
    return model.encode("query: " + text, normalize_embeddings=True).tolist()
```

### API 계약
| 제공 | 주소 | 용도 |
|---|---|---|
| api | GET / | PC 대시보드 |
| api | POST /api/sessions | 세션 생성 → {"session_id", "url", "qr_png"(base64)} |
| api | GET /api/sessions/{id} | {"session_id", "connected"} |
| api | GET /m/{session_id} | 모바일 촬영 페이지 (열리면 connected=true) |
| api | POST /api/upload?session_id=... | multipart 필드명 `file`, 사진 1장 |
| api | GET /api/passages?session_id=... | 목록 (embedding 제외) |
| api | POST /api/search | {"query"} → rag로 그대로 중계 |
| rag | POST http://rag:8001/search | 실제 검색 |

```json
POST /search 요청  {"query": "Q3 총 처리량은 얼마야?"}
응답  {"answer": "...", "sources": [{"id": 3, "card_no": 4, "content": "...", "score": 0.82}]}
```

### 공통 원칙
- 하루 안에 끝내야 하므로 기능은 최소, 코드는 단순하고 읽기 쉽게. 불필요한 추상화·프레임워크 금지.
- 위 계약(스키마, 상태 값, API 형식, 환경변수 이름)을 임의로 바꾸지 말 것. 바꿔야 할 이유가 있으면 코드 대신 "계약 변경 제안"으로 따로 알려줄 것.
- 라이브러리 버전은 requirements.txt에 고정(pin)하고, 확신이 없는 최신 API는 쓰지 말 것.

## 내 작업: worker 컨테이너

### 만들 파일
`worker/Dockerfile`, `worker/requirements.txt`, `worker/worker.py`, `worker/ocr_engine.py`, `worker/test_local.py`

### 입력 사진의 특징
- 스마트폰으로 PC 모니터를 찍은 사진 (모아레, 반사광, 약간의 기울기, 회전 가능).
- 아이폰은 HEIC일 수 있음. EXIF 회전 정보가 있을 수 있음.
- 카드 한 장에 3자리 카드 번호(예: `004`), 영어 제목, 영어 본문 단락 1~4개가 있다. 지문은 영어다.
- 원본 해상도가 커서(4000px급) CPU OCR이 느리다.

### 요구사항

**OCR 엔진 분리 (`ocr_engine.py`)**
- `run_ocr(img: PIL.Image) -> str` 하나만 외부에 노출한다. 결과는 위에서 아래, 왼쪽에서 오른쪽 순서로 줄을 정렬해 줄바꿈으로 이은 문자열.
- 환경변수 `OCR_ENGINE`로 선택:
  - `paddle` (기본): PaddleOCR, `lang='en'`, CPU. PaddleOCR은 2.x와 3.x의 API가 다르므로 **네가 확실히 아는 한 가지 버전 조합(paddlepaddle + paddleocr)을 골라 requirements.txt에 고정하고 그 버전의 API만 사용**해. 어떤 버전을 골랐는지와 이유를 답변에 명시해.
  - `gemini` (Plan B): `google-genai` SDK로 이미지를 Gemini에 보내 "이미지 속 텍스트를 그대로 옮겨 적어라. 설명 없이 텍스트만" 지시. 모델명은 환경변수 `GEMINI_MODEL`로 받기.
  - `fake`: PaddleOCR이 준비되기 전 연결 테스트용. 실제 OCR 대신 `/app/demo/passages.json`의 원문을 호출할 때마다 순서대로 하나씩 돌려준다 (`f"{card_no:03d}\n{title}\n{body}"` 형식). 그래서 사진은 실제로 찍고, 뒤 단계(카드 번호 처리, 임베딩, 검색)도 실제와 같은 글로 테스트할 수 있다.
- 모델은 프로세스 시작 시 한 번만 로딩.

**이미지 전처리**
- `pillow-heif` 등록해서 HEIC 열기, `ImageOps.exif_transpose`로 회전 보정, RGB 변환, 긴 변 1600px로 축소.

**카드 번호 추출과 중복 처리**
- OCR 결과 앞쪽 몇 줄에서 정규식으로 001~100 사이 3자리 숫자를 찾아 `card_no`(int)로 저장. 못 찾으면 None.
- card_no가 있고 같은 card_no의 `done` row가 이미 있으면:
  - 새 content가 더 길면 → 새 row를 `done`, 기존 row를 `duplicate`
  - 아니면 → 새 row를 `duplicate` (임베딩 생략 가능)
- card_no가 None이면 중복 처리 없이 `done`.
- 카드 번호 줄은 content에서 제거하지 않아도 됨 (단순하게).

**메인 루프 (`worker.py`)**
- 시작 시: `status='processing'`인 row를 전부 `uploaded`로 되돌림 (이전에 죽은 worker가 남긴 것).
- 1초 간격 polling: `status='uploaded'`를 `created_at` 오름차순으로 1개 조회 → `processing`으로 update → Storage `uploads`에서 `image_path` 다운로드 → 전처리 → `run_ocr` → 공백 정리 → 카드 번호·중복 처리 → `embed_passage(content)` → `content, card_no, embedding, status` update.
- OCR 결과가 비었거나 너무 짧으면(예: 20자 미만) `failed`, error="텍스트를 거의 읽지 못함".
- 예외 발생 시 해당 row를 `failed`로, error에 예외 메시지(500자 이내) 저장하고 루프는 계속.
- 처리마다 한 줄 로그: id, card_no, 글자 수, 소요 시간, 최종 상태.
- worker는 1개만 실행한다고 가정 (복잡한 락 불필요).

**test_local.py**
- `python worker/test_local.py 사진경로` 로 DB 없이 전처리 + OCR + 카드 번호 추출 결과만 출력. OCR 품질 튜닝용.

**Dockerfile**
- `python:3.11-slim`, build context는 프로젝트 루트. `COPY shared/ /app/shared/`, `COPY worker/ /app/worker/`, `COPY demo/ /app/demo/`.
- PaddleOCR·OpenCV에 필요한 시스템 라이브러리 설치 (예: libgl1, libglib2.0-0, libgomp1).
- torch는 CPU 전용으로: `pip install torch --index-url https://download.pytorch.org/whl/cpu` 를 먼저 설치한 뒤 나머지 requirements 설치.
- PaddleOCR과 torch(sentence-transformers)가 같이 들어가므로 numpy 버전 충돌이 없도록 버전을 맞춰서 고정.
- 모델 캐시 경로: `/root/.cache`(HuggingFace), `/root/.paddleocr`, `/root/.paddlex` (compose에서 볼륨으로 연결됨).
- 실행: `python -m worker.worker`

### 출력 형식
1. 위 5개 파일을 각각 완전한 코드로 (생략 없이).
2. 고른 PaddleOCR 버전과 이유, 알려진 설치 함정.
3. 단독 테스트 순서: `OCR_ENGINE=fake`로 DB 연결과 실제 원문 흐름 확인 → `test_local.py`로 실제 사진 OCR 확인 → `paddle`로 전체 루프.
4. 빌드가 실패하거나 너무 오래 걸릴 때 `OCR_ENGINE=gemini`로 전환하는 방법.

### 완료 기준
- `uploaded` row가 생기면 수 초 안에 `done`(또는 `duplicate`/`failed`)으로 바뀌고, `content`와 `card_no`, `embedding`이 채워진다.
- 같은 카드를 두 번 찍으면 하나만 `done`으로 남는다.
- worker를 중간에 재시작해도 `processing`에 멈춘 row가 없다.
