# [A] api 컨테이너 생성 프롬프트

아래 전체를 복사해서 LLM에 그대로 붙여넣으세요.

---

너는 FastAPI와 바닐라 HTML/JS에 능숙한 백엔드 개발자야. 아래 공통 컨텍스트를 지키면서 `api` 컨테이너를 완성해줘. 나는 A 담당이고, `worker`와 `rag`는 다른 팀원이 만들고 있어.

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

## 내 작업: api 컨테이너

### 만들 파일
`api/Dockerfile`, `api/requirements.txt`, `api/main.py`, `api/static/dashboard.html`, `api/static/mobile.html`

### 요구사항

**공통**
- `shared/sb.py`만 import한다. `shared/embed.py`는 import하지 않는다 (불필요한 모델 로딩 방지).
- uvicorn으로 `0.0.0.0:8000` 실행 (같은 Wi-Fi의 폰이 접속해야 함).
- 프론트는 외부 CDN 없이 바닐라 HTML/JS/CSS. QR 이미지는 서버에서 Python `qrcode` 라이브러리로 PNG를 만들어 base64로 내려준다.
- `SUPABASE_SERVICE_KEY`는 HTML/JS에 절대 들어가면 안 된다. 브라우저와 폰은 오직 이 서버의 `/api/*`만 호출한다.

**세션·QR**
- `POST /api/sessions`: 짧은 랜덤 id(`secrets.token_urlsafe(6)` 정도) 생성 → `sessions`에 insert → `url = PUBLIC_BASE_URL + "/m/" + id`로 QR 생성 → `{"session_id", "url", "qr_png"}` 반환.
- `GET /api/sessions/{id}`: `{"session_id", "connected"}` 반환.
- `GET /m/{session_id}`: 세션이 있으면 `connected=true`로 업데이트하고 `mobile.html`을 반환 (없으면 404 안내 문구).

**업로드**
- `POST /api/upload?session_id=...`: multipart `file` 1장. 이미지 타입만 허용, 15MB 제한.
- Storage 경로는 `{uuid4}{원래 확장자 소문자}` (확장자 없으면 `.jpg`). 한글 파일명을 Storage 키로 쓰지 말 것.
- `sb.storage.from_("uploads").upload(path, bytes, {"content-type": file.content_type})` 후 `passages`에 `{session_id, filename(원래 이름), image_path, status: "uploaded"}` insert.
- 응답: `{"id", "status": "uploaded"}`.

**목록**
- `GET /api/passages?session_id=...`: `id, card_no, filename, status, content, error, created_at`만 select (`embedding` 절대 제외), 최신순. session_id가 없으면 전체 최근 50개.

**검색 중계**
- `POST /api/search`: 요청 body를 그대로 `RAG_URL/search`로 전달. `httpx.AsyncClient(timeout=30)` 사용 (Gemini 응답이 느려서 기본 5초면 끊김). rag 오류 시 502와 사람이 읽을 수 있는 메시지.
- rag는 다른 팀원이 만들고 있어서 아직 없을 수 있다. 환경변수 `RAG_MOCK=1`이면 rag를 호출하지 않고 API 계약과 똑같은 형식의 고정 응답을 1초 지연 후 반환한다: `{"answer": "(mock) Q3 총 처리량은 1,482,600개입니다. [카드 004]", "sources": [{"id": 0, "card_no": 4, "content": "Total throughput for Q3 reached 1,482,600 units ...", "score": 0.87}]}`. 대시보드 검색 화면은 이 mock으로 먼저 완성하고, rag가 준비되면 `RAG_MOCK`만 지워서 실제로 전환한다.

**dashboard.html (PC, `GET /`)**
- 페이지 로드 시 세션 생성 → 왼쪽 상단에 QR 이미지와 URL 텍스트 표시.
- 2초마다 세션 상태 조회 → "폰 연결 대기 중" / "연결됨" 표시.
- 2초마다 `/api/passages?session_id=...` 조회 → 표(카드 번호, 파일명, 상태 배지, OCR 내용 앞 120자, 오류). 상태별 개수 요약(uploaded/processing/done/duplicate/failed)도 상단에 표시.
- 검색창 + 버튼 → `/api/search` 호출 → 로딩 표시 → 답변과 근거 지문(카드 번호, 점수, 내용 앞부분) 표시.
- "새 세션" 버튼(새 QR 발급).
- 이 탭을 백그라운드로 보냈다가 돌아와도 정상 갱신되어야 함.

**mobile.html (폰, `GET /m/{session_id}`)**
- 화면 대부분을 차지하는 큰 "촬영" 버튼 하나. 내부적으로 `<input type="file" accept="image/*" capture="environment">`를 쓴다 (HTTPS 없이 동작해야 하므로 `getUserMedia`는 쓰지 말 것).
- 촬영 즉시 자동 업로드(FormData, 필드명 `file`, URL의 session_id 사용) → "업로드 중…" → "완료 ✓ (n장째)" 표시 → 같은 input을 초기화해서 바로 다시 촬영 가능.
- 업로드 실패 시 에러 문구와 재시도 버튼.
- 모바일 뷰포트 메타 태그, 큰 글씨, 한 손으로 쓰기 쉬운 레이아웃.

**Dockerfile**
- `python:3.11-slim`, build context는 프로젝트 루트. `COPY shared/ /app/shared/`, `COPY api/ /app/api/`. 실행: `uvicorn api.main:app --host 0.0.0.0 --port 8000`.

### 출력 형식
1. 위 5개 파일을 각각 완전한 코드로 (생략 없이).
2. 단독 테스트 방법: `rag` 없이도 확인할 수 있는 curl 명령 (세션 생성, 사진 업로드, 목록 조회).
3. 폰에서 접속이 안 될 때 확인할 체크리스트 (같은 Wi-Fi, PC 방화벽 8000 포트, PUBLIC_BASE_URL이 localhost가 아닌지, 공용 Wi-Fi 기기 간 통신 차단 시 핫스팟).

### 완료 기준
- PC에서 `http://localhost:8000` 접속 시 QR이 보인다.
- 폰으로 QR을 찍으면 모바일 페이지가 열리고 대시보드가 "연결됨"으로 바뀐다.
- 폰으로 촬영하면 대시보드 표에 `uploaded` 행이 2초 안에 나타난다.
