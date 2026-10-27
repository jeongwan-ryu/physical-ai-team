# [C] rag 컨테이너 + 공통 세팅 생성 프롬프트

아래 전체를 복사해서 LLM에 그대로 붙여넣으세요.

---

너는 RAG 시스템과 Docker Compose 구성에 능숙한 개발자야. 아래 공통 컨텍스트를 지키면서 `rag` 컨테이너와 팀 공통 세팅 파일을 완성해줘. 나는 C 담당(리드)이고, `api`와 `worker`는 다른 팀원이 만들고 있어.

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

## 내 작업 1: 공통 세팅

### 만들 파일
`sql/schema.sql`, `shared/__init__.py`, `shared/sb.py`, `shared/embed.py`, `docker-compose.yml`, `.env.example`, `.gitignore`, `scripts/extract_passages.py`

- `sql/schema.sql`: 공통 컨텍스트의 스키마 그대로 + 맨 위에 `create extension if not exists vector;`. Supabase SQL Editor에 한 번에 붙여넣어 실행할 수 있게.
- `shared/sb.py`, `shared/embed.py`: 공통 컨텍스트 코드 그대로.
- `docker-compose.yml`:
  - api: build context `.`, dockerfile `api/Dockerfile`, ports `8000:8000`, env_file `.env`, environment `RAG_URL=http://rag:8001`
  - worker: build context `.`, dockerfile `worker/Dockerfile`, env_file `.env`, volumes `./models/hf:/root/.cache`, `./models/paddleocr:/root/.paddleocr`, `./models/paddlex:/root/.paddlex`, `restart: unless-stopped`
  - rag: build context `.`, dockerfile `rag/Dockerfile`, env_file `.env`, volumes `./models/hf:/root/.cache`, 포트는 외부에 열지 않음
- `.env.example`: 공통 컨텍스트의 변수 + `GEMINI_MODEL`, `OCR_ENGINE=paddle` (값은 비워두기)
- `.gitignore`: `.env`, `models/`, `__pycache__/` 등
- `scripts/extract_passages.py`: `demo/ocr-conveyor-test.html` 안의 `const PASSAGES = [...]` 배열(각 항목 `{ title: "...", body: ["단락", ...] }`, 마지막 항목 뒤 trailing comma 있음, 문자열 안에 이스케이프된 따옴표 있음)을 파싱해서 `demo/passages.json`(`[{"card_no": 순번(1부터), "title", "body": 단락들을 공백으로 이은 문자열}]`)으로 저장. 정규식이나 간단한 JS→JSON 변환으로 견고하게.

## 내 작업 2: rag 컨테이너

### 만들 파일
`rag/Dockerfile`, `rag/requirements.txt`, `rag/main.py`, `rag/seed.py`

### 요구사항

**`POST /search`** (FastAPI, `0.0.0.0:8001`)
- 입력 `{"query": str}`. 빈 문자열이면 400.
- `embed_query(query)` → `sb.rpc("match_passages", {"query_embedding": q, "match_count": 5}).execute()`.
- 결과가 0개면 Gemini를 호출하지 않고 `{"answer": "아직 검색 가능한 지문이 없습니다. 먼저 카드를 촬영해 주세요.", "sources": []}`.
- 유사도 기준값으로 거르지 않는다 (e5는 무관한 글도 0.7~0.8이 나와 기준값이 잘 안 맞음). 관련성 판단은 프롬프트에 맡긴다.
- Gemini 호출: `google-genai` SDK, 모델명은 환경변수 `GEMINI_MODEL`. 프롬프트 요지:
  - 아래 지문들은 영어 카드를 OCR한 결과라 오탈자가 있을 수 있다.
  - 지문 내용만 근거로 한국어로 간결하게 답하라. 숫자·고유명사는 지문 표기 그대로.
  - 답의 근거가 된 카드 번호를 `[카드 004]` 형식으로 표시하라.
  - 근거가 없으면 "제공된 지문에서 찾을 수 없습니다"라고 답하라.
  - 각 지문은 `[카드 {card_no:03d}] {content}` 형식으로 번호를 붙여 전달 (card_no가 없으면 `[카드 ?]`).
- 응답: `{"answer", "sources": [{"id", "card_no", "content", "score"}]}` (score는 소수 둘째 자리 반올림).
- Gemini 오류·타임아웃 시 500 대신 `answer`에 "답변 생성 중 오류가 발생했습니다: ..."를 담고 sources는 그대로 반환 (검색 결과라도 보이게).
- 환경변수 `RAG_FAKE=1`이면 Gemini 호출 없이 `answer="(테스트) 검색은 정상 동작합니다"` + 실제 검색 결과 반환 (11시 연결 테스트용).
- `GET /health` → `{"ok": true}`.
- 임베딩 모델은 서버 시작 시 한 번만 로딩 (import 시점 로딩이면 그대로 둬도 됨).

**`seed.py`**
- `python -m rag.seed --limit 20` : `demo/passages.json`에서 앞 N개를 `content = title + " " + body`로 임베딩해서 `passages`에 `status='done'`, `card_no`, `filename="seed"`로 insert. worker 없이 검색을 먼저 테스트하기 위한 용도.
- `--clear` 옵션: `filename='seed'`인 row만 삭제.

**Dockerfile**
- `python:3.11-slim`, build context는 프로젝트 루트. `COPY shared/ /app/shared/`, `COPY rag/ /app/rag/`, `COPY demo/ /app/demo/`.
- torch는 CPU 전용으로 먼저 설치: `pip install torch --index-url https://download.pytorch.org/whl/cpu`
- 실행: `uvicorn rag.main:app --host 0.0.0.0 --port 8001`

### 출력 형식
1. 공통 세팅 파일과 rag 파일 전부, 각각 완전한 코드로 (생략 없이).
2. 전날 세팅 순서: Supabase 프로젝트 생성 → `schema.sql` 실행 → `uploads` 버킷 생성 → `.env` 작성 → `extract_passages.py` 실행 → `docker compose build`.
3. 단독 테스트 순서: `seed.py`로 원문 20개 넣기 → `RAG_FAKE=1`로 검색 결과 확인 → Gemini 연결 → 아래 예시 질문으로 확인.
   - "Q3 총 처리량은 얼마야?" (기대: 1,482,600, Quarterly Operations Summary)
   - "How far do barn swallows travel for winter?" (기대: 9,000 km)
   - "주전자 석회 제거는 얼마나 자주 해야 해?" (기대: 3개월, Instructions for the New Kettle)
4. Supabase에서 `vector` 컬럼에 Python list를 insert/rpc로 넘길 때 주의점이 있다면 알려줘.

### 완료 기준
- `seed.py` 실행 후 `curl -X POST http://localhost:8001/search` (테스트 시에만 포트 임시 개방) 또는 `docker compose exec rag` 안에서 호출하면 근거 카드 번호가 포함된 한국어 답변이 나온다.
- 지문이 0개일 때도 에러 없이 안내 문구가 나온다.
- `docker compose up --build`로 세 컨테이너가 함께 뜬다.
