# OCR + RAG 검색 시스템 (하루 프로젝트, Supabase 버전)

## 목표

PC 대시보드의 QR을 폰으로 찍어 연동 → 폰 카메라로 모니터의 컨베이어 페이지(`ocr-conveyor-test.html`)를 촬영 → OCR → 저장 → 질문하면 관련 지문을 찾아 답변까지, 한 번 끝까지 도는 것.

## 전체 구조 (한 줄 요약)

**`api`가 QR 연동과 업로드를 받고, `worker`가 OCR·임베딩을 처리하고, `rag`가 검색·답변을 만들고, 세 컨테이너 모두 같은 Supabase 프로젝트(DB + Storage)를 사용한다.**

| 구성 요소 | 담당 | 하는 일 |
|---|---|---|
| `api` 컨테이너 | A | PC 대시보드, QR 연동, 모바일 촬영 페이지, 업로드, 검색창 |
| `worker` 컨테이너 | B | OCR(PaddleOCR, 영어), 카드 번호 추출·중복 처리, 임베딩, DB 저장 |
| `rag` 컨테이너 | C | 비슷한 지문 찾기, Gemini로 답변 생성 |
| Supabase | C | `sessions`, `passages` 테이블(Postgres + pgvector), `uploads` 버킷(Storage) |
| `ocr-conveyor-test.html` | - | 촬영 대상. 영어 지문 100개가 번호(001~100)와 함께 흘러가는 페이지 |

### 화면 배치 (PC 모니터 1대, 브라우저 탭 2개)

- 탭 1: 대시보드 (QR, 처리 현황, 검색창)
- 탭 2: 컨베이어 페이지 (촬영 대상, `F11` 전체화면 권장)
- 스마트폰: QR로 연결된 모바일 촬영 페이지

사용 순서: 탭 1에서 QR 연동 → 탭 2로 전환해 전체화면으로 촬영 → 탭 1로 돌아와 처리 현황 확인 → 검색

- 촬영할 때는 컨베이어 탭만 화면에 보이게 하기 (대시보드 글자가 같이 찍히면 OCR 결과에 섞임)
- 화면 분할(좌우 배치)도 가능하지만 카드가 작아져 인식률이 떨어지므로, 쓸 경우 폰으로 컨베이어 쪽만 꽉 차게 찍기
- 대시보드 탭이 뒤에 있어도 처리는 계속 진행되고, 탭으로 돌아오면 2초 안에 최신 상태로 갱신됨

### 연동·촬영 흐름

1. PC 대시보드 접속 → `api`가 세션 생성 → QR 표시 (`http://{PC LAN IP}:8000/m/{session_id}`)
2. 폰으로 QR 촬영 → 모바일 촬영 페이지 열림 → 대시보드에 "연결됨" 표시
3. 폰에서 촬영 버튼 → 폰 기본 카메라로 모니터의 컨베이어 페이지 촬영 → 업로드
4. `api`가 Storage에 저장하고 `passages`에 `uploaded`로 insert
5. `worker`가 OCR → 카드 번호 추출 → 중복 확인 → 임베딩 → `done`
6. 대시보드가 2초마다 상태 조회해서 표시

### 질문 처리 흐름

1. 대시보드 검색창에 질문 입력
2. `api`가 `rag`에 전달 (컨테이너끼리 직접 통신하는 건 이것 하나뿐)
3. `rag`가 질문을 임베딩해서 `match_passages`로 가장 비슷한 지문 5개 조회
4. 지문 5개 + 질문을 Gemini에 보내 한국어 답변 받기
5. 답변과 근거 지문(카드 번호 포함)을 대시보드에 표시

---

## 기술 스택

| 항목 | 선택 |
|---|---|
| 백엔드 | FastAPI |
| QR 생성 | Python `qrcode` |
| 모바일 촬영 | `<input type="file" accept="image/*" capture="environment">` (HTTP에서도 동작) |
| DB | Supabase Postgres |
| 이미지 저장 | Supabase Storage (`uploads` 버킷, private) |
| OCR | PaddleOCR (`lang='en'`, 지문이 영어), Plan B: Gemini에 이미지 직접 전달 |
| 임베딩 | `intfloat/multilingual-e5-small` (384차원, 최대 512토큰) |
| 벡터 검색 | pgvector (`match_passages` SQL 함수) |
| LLM | Gemini Flash (답변은 한국어) |
| 실행 | docker-compose |

### 하루 프로젝트라서 뺀 것 (평가 쪽에 범위 미리 확인)

- 폰 화면 안 실시간 카메라 프리뷰·연속 촬영 (`getUserMedia`는 HTTPS 필수라 제외, 폰 기본 카메라로 한 장씩 촬영)
- 복잡한 프레임 병합 → 카드 번호 기준 중복 처리로 단순화
- 키워드 검색(BM25) → 시간 남으면 추가
- Supabase Realtime → 2초 polling으로 대체

---

## 확정 사항 (리드가 결정, 팀원은 그대로 따르기)

아래 값은 모두 확정된 내용입니다. 변경이 필요하면 리드에게 먼저 이야기하고, 리드가 이 문서를 수정한 뒤 공유합니다.

### 1. 폴더 구조

```
project/
├── docker-compose.yml
├── .env                  # Supabase URL/키, Gemini 키, PC 주소 (Git에 올리지 않기)
├── models/               # 모델 캐시 (재다운로드 방지)
│   ├── hf/               # e5 (HuggingFace)
│   ├── paddleocr/        # PaddleOCR 2.x
│   └── paddlex/          # PaddleOCR 3.x
├── shared/               # C 관리
│   ├── sb.py             # Supabase 클라이언트 (셋 다 사용)
│   └── embed.py          # 임베딩 함수 (worker, rag만 사용)
├── demo/                 # A 관리
│   ├── ocr-conveyor-test.html
│   ├── passages.json     # 정답 원문 (PASSAGES 배열 추출)
│   └── questions.json    # 데모 질문·정답
├── api/      (A)  Dockerfile, main.py, static/dashboard.html, static/mobile.html
├── worker/   (B)  Dockerfile, worker.py
└── rag/      (C)  Dockerfile, main.py
```

- `api`는 `shared/sb.py`만 import (`embed.py`를 import하면 쓰지도 않는 모델을 로딩함)

### 2. Supabase 세팅 (C가 전날 완료)

- Supabase 프로젝트 생성, 팀원 둘을 Organization에 초대
- SQL Editor에서 아래 SQL 실행
- Storage에서 `uploads` 버킷 생성 (private)
- Project Settings → API에서 `URL`, `service_role` 키 복사 → `.env` 작성 후 팀원에게 따로 전달

```sql
create extension if not exists vector;

create table sessions (
  id text primary key,            -- QR에 들어가는 session_id
  connected boolean default false,-- 폰이 모바일 페이지를 열면 true
  created_at timestamptz default now()
);

create table passages (
  id bigint generated always as identity primary key,
  session_id text references sessions(id),
  card_no int,                    -- 카드 번호 (001~100), OCR에서 추출
  filename text,                  -- 업로드 파일명 (대시보드 표시용)
  image_path text,                -- Storage 안의 경로 ({uuid}.jpg)
  status text default 'uploaded', -- uploaded | processing | done | duplicate | failed
  content text,                   -- OCR 결과
  embedding vector(384),
  error text,                     -- 실패 이유
  created_at timestamptz default now()
);

create or replace function match_passages(query_embedding vector(384), match_count int)
returns table (id bigint, card_no int, content text, score float)
language sql stable as $$
  select id, card_no, content, 1 - (embedding <=> query_embedding) as score
  from passages
  where status = 'done'
  order by embedding <=> query_embedding
  limit match_count;
$$;
```

### 3. `.env` 형식

```
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_SERVICE_KEY=eyJ...
GEMINI_API_KEY=...
PUBLIC_BASE_URL=http://192.168.0.10:8000   # 데모 PC의 LAN IP (QR에 들어감)
```

- `.env`는 `.gitignore`에 추가, 메신저 등으로 따로 공유
- `service_role` 키는 컨테이너(서버)에서만 사용, HTML·JavaScript에 절대 넣지 않기
- `PUBLIC_BASE_URL`은 `localhost` 금지 (폰에서 localhost는 폰 자신)

### 4. 상태 값

| 값 | 누가 바꿈 | 의미 |
|---|---|---|
| `uploaded` | A | 업로드 완료, 처리 대기 |
| `processing` | B | OCR·임베딩 중 |
| `done` | B | 검색 가능 |
| `duplicate` | B | 같은 카드 번호가 이미 `done`으로 있음 (검색 제외) |
| `failed` | B | 실패 (`error`에 이유) |

- `match_passages`는 `done`만 검색
- worker 시작 시 `processing`으로 남아 있는 row는 `uploaded`로 되돌림

### 5. 카드 번호 중복 처리 규칙

- OCR 결과 맨 앞쪽에서 3자리 숫자(`001`~`100`)를 찾아 `card_no`에 저장
- 같은 `card_no`의 `done` row가 이미 있으면: 새 결과의 글자 수가 더 길면 새 것을 `done`, 기존 것을 `duplicate`로 / 아니면 새 것을 `duplicate`로
- 번호를 못 읽으면 `card_no`는 비워두고 그냥 `done` (중복 처리 생략)

### 6. 공통 모듈

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

- B는 저장할 때 `embed_passage()`, C는 검색할 때 `embed_query()`만 사용
- 임베딩은 `list[float]` 그대로 insert / rpc에 넘김 (오전 첫 연결 테스트에서 실제로 1건 insert 확인)

### 7. API 주소와 형식

| 누가 제공 | 주소 | 용도 |
|---|---|---|
| A | `GET /` | PC 대시보드 |
| A | `POST /api/sessions` | 세션 생성 → `{session_id, qr_png(base64), url}` |
| A | `GET /api/sessions/{id}` | 폰 연결 여부 확인 (대시보드가 polling) |
| A | `GET /m/{session_id}` | 모바일 촬영 페이지 (열리면 `connected=true`) |
| A | `POST /api/upload?session_id=...` | 폰에서 촬영한 사진 업로드 |
| A | `GET /api/passages?session_id=...` | 대시보드용 목록 |
| A | `POST /api/search` | 대시보드 → A → C로 전달 |
| C | `POST http://rag:8001/search` | 실제 검색 (내부 전용) |

```json
요청  {"query": "Q3 총 처리량은 얼마야?"}
응답  {"answer": "...",
       "sources": [{"id": 3, "card_no": 4, "content": "...", "score": 0.82}]}
```

- 브라우저·폰은 `api`(8000)만 호출, `rag`(8001)는 외부에 안 열기
- `/api/passages`는 `id, card_no, filename, status, content, error, created_at`만 조회 (`embedding` 제외)
- `api` → `rag` 호출은 `httpx` 타임아웃 30초

### 8. docker-compose

```yaml
services:
  api:
    build: { context: ., dockerfile: api/Dockerfile }
    ports: ["8000:8000"]          # 0.0.0.0으로 열려서 같은 Wi-Fi의 폰이 접속 가능
    env_file: .env
    environment: [RAG_URL=http://rag:8001]

  worker:
    build: { context: ., dockerfile: worker/Dockerfile }
    env_file: .env
    volumes:
      - ./models/hf:/root/.cache
      - ./models/paddleocr:/root/.paddleocr
      - ./models/paddlex:/root/.paddlex

  rag:
    build: { context: ., dockerfile: rag/Dockerfile }
    env_file: .env
    volumes: ["./models/hf:/root/.cache"]
```

- `context: .`로 둔 이유: 각 Dockerfile에서 `COPY shared/ /app/shared/`가 되게 하려고
- torch는 CPU 전용으로 설치: `pip install torch --index-url https://download.pytorch.org/whl/cpu`
- worker는 PaddleOCR과 torch가 같이 들어가므로 numpy 버전 충돌 주의 (전날 빌드해서 확인)

### 9. 촬영 조건 (단계별로 올리기)

| 단계 | 컨베이어 페이지 설정 |
|---|---|
| 1단계 (기본 성공) | 투입 지문 10장, 흰 종이/검은 글씨, 정지 상태에서 촬영 |
| 2단계 | 느린 속도로 재생하면서 촬영 |
| 3단계 (발표용 비교) | 속도 올리기, 미색·검은 카드·저대비 테마로 인식률 비교 |

- 모니터 밝기는 높이고 화면에 정면으로, 반사광 없게 촬영
- 카드 한 장이 화면을 꽉 채우도록 글자 크기·카드 높이 조절

### 10. 시작 전 확인 (각자)

- [ ] `.env` 받아서 `docker compose up --build`로 세 컨테이너가 뜨는지 확인
- [ ] 각 컨테이너에서 Supabase 접속 테스트 (`sb.table("passages").select("id").execute()`)
- [ ] `localhost:8000`에서 빈 페이지라도 열리는지 확인
- [ ] 각자 브랜치 만들고 작업 시작

---

## 11시 목표: 실제 촬영으로 한 바퀴 (OCR만 임시 대체 가능)

입력은 처음부터 진짜를 씁니다. 컨베이어 페이지가 실제 테스트 데이터이고 `passages.json`이 정답이므로 가짜 사진이나 가짜 글은 필요 없습니다. 임시로 대체하는 것은 아직 준비가 안 된 **처리 단계**뿐입니다.

- [ ] A: 대시보드 QR → 폰 연동 → 컨베이어 페이지 실제 촬영 → `uploaded` row 생성
- [ ] B: PaddleOCR이 아직 안 됐으면 `OCR_ENGINE=fake`로 실행 (fake는 `passages.json`의 원문을 순서대로 돌려줌) → 임베딩 저장 → `done`
- [ ] C: `seed.py`로 실제 원문 20개를 넣어두고 Gemini 연결 전이면 `RAG_FAKE=1`로 검색 결과 반환
- [ ] 폰 촬영 → 대시보드에서 `done` 확인 → 검색 결과 표시까지 한 번 성공
- [ ] PaddleOCR이 준비되는 대로 `OCR_ENGINE=paddle`로 바꾸고 같은 흐름을 다시 확인

---

## A: `api`

PC 대시보드, QR 연동, 모바일 촬영 페이지, 업로드·검색 API, 데모 준비 담당.

- [ ] FastAPI로 대시보드(`/`)와 모바일 페이지(`/m/{session_id}`) 띄우기
- [ ] **QR 연동**: 세션 생성 → `PUBLIC_BASE_URL/m/{session_id}`로 QR 생성 → 대시보드에 표시 → 폰이 열면 `connected=true` → 대시보드에 "연결됨" 표시
- [ ] **모바일 페이지**: 큰 촬영 버튼 하나 (`capture="environment"`) → 촬영 즉시 업로드 → "업로드 완료" 표시 후 다시 촬영 가능
- [ ] **업로드**: Storage에 `{uuid}.jpg`로 저장 → `passages`에 `session_id`와 함께 `uploaded`로 insert
- [ ] **대시보드**: 2초마다 `/api/passages` 조회해서 카드 번호·상태·OCR 글자 표로 표시 (`embedding` 제외)
- [ ] **검색창**: 질문 입력 → `rag` 호출(타임아웃 30초) → 답변과 근거 지문(카드 번호) 표시
- [ ] **데모 세트**: 컨베이어 페이지의 `PASSAGES` 배열을 `passages.json`으로 추출, 숫자가 들어간 지문 위주로 질문·정답 10개 작성 (예: Q3 총 처리량 → 1,482,600 / 제비 월동 거리 → 9,000km / 주전자 석회 제거 주기 → 3개월)
- [ ] **데모 녹화**: QR 연동부터 답변까지 3~5분 화면 녹화 (라이브 시연 실패 대비)

## B: `worker`

OCR, 카드 번호 처리, 임베딩 파이프라인 담당.

- [ ] 시작 시 `processing` → `uploaded` 되돌리기
- [ ] PaddleOCR(`lang='en'`)로 폰으로 찍은 모니터 사진 한 장 글자 읽기 테스트 (설치된 버전의 API 확인)
- [ ] 이미지 열기: 아이폰 HEIC 대비 `pillow-heif` 설치, 사진 회전(EXIF) 보정
- [ ] OCR 전에 이미지 긴 변을 1600px 정도로 축소
- [ ] **카드 번호**: OCR 결과에서 3자리 번호 추출 → 중복 처리 규칙대로 `done` / `duplicate`
- [ ] **반복 루프**: 1초마다 `uploaded` 조회 → `processing` → 다운로드 → 축소 → OCR → 번호 추출·중복 확인 → `embed_passage()` → 저장
- [ ] 실패하면 `failed` + `error` 기록하고 다음 사진으로 넘어가기
- [ ] **Plan B**: 12시까지 PaddleOCR이 안 되면 Gemini에 이미지를 보내 글자 추출로 전환
- [ ] 여유 되면: `passages.json`과 비교해서 OCR 정확도(`difflib` 유사도) 계산 → 대시보드·발표에 활용

## C: `rag` + Supabase + 공통 세팅 (리드)

Supabase 프로젝트, 공통 모듈, docker-compose, 검색·답변 생성 담당.

- [ ] **전날**: Supabase 세팅(테이블, 함수, 버킷), `.env`, `shared/`, docker-compose 작성해서 공유
- [ ] `passages.json`의 원문 10~20개를 임베딩해서 `done`으로 직접 넣고 검색 테스트
- [ ] **검색**: `embed_query()` → `sb.rpc("match_passages", {"query_embedding": q, "match_count": 5})`
- [ ] **답변**: 지문 5개 + 질문을 Gemini에 보내기 ("아래 영어 지문만 근거로 한국어로 답하고, 근거가 없으면 모른다고 답해")
- [ ] 한국어 질문과 영어 질문 둘 다 테스트 (지문이 영어라 영어 질문이 검색 정확도가 더 높음)
- [ ] 유사도 기준값으로 거르지 않음, 판단은 Gemini 프롬프트에 맡김
- [ ] 지문이 하나도 없을 때 에러 없이 안내 문구 반환

---

## 하루 일정

| 시간 | 할 일 |
|---|---|
| 09–09:30 | 리드가 확정 사항과 업무 분담 공유, 각자 `.env` 받아 Supabase 접속 확인 |
| 09:30–11 | 실제 촬영으로 한 바퀴 연결 (QR 연동 포함, OCR은 준비 안 됐으면 fake) |
| 11–13 | 각자 진짜 기능 구현 (12시에 PaddleOCR 상태 점검, 안 되면 Plan B) |
| 13–14 | 점심 |
| 14–16 | 촬영 조건 1단계로 end-to-end 확인, 데모 질문으로 검색 품질 확인 |
| 16–18 | 2·3단계 조건 테스트, 버그 수정, 데모 녹화 |

## 전날 꼭 할 것

- [ ] 평가 쪽에 범위(연속 촬영·키워드 검색 제외)로 괜찮은지 확인
- [ ] Supabase 프로젝트 생성 + 테이블·함수·버킷 세팅 (무료 플랜 일시정지 여부 확인)
- [ ] PaddleOCR, e5 모델 미리 다운로드 / Docker 이미지 미리 빌드 (특히 worker 이미지)
- [ ] Gemini API 키 발급
- [ ] 작업 장소 인터넷 확인 (Supabase가 클라우드라 필수)
- [ ] **폰 연결 테스트**: 데모 PC와 폰이 같은 Wi-Fi인지, 폰에서 `http://{PC IP}:8000` 접속되는지 (안 되면 PC 방화벽에서 8000 포트 허용, 공용 Wi-Fi는 기기 간 통신이 막혀 있을 수 있으니 핫스팟 준비)
