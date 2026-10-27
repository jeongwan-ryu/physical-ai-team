# OCR + RAG 검색 시스템

PC 대시보드의 QR을 폰으로 찍어 연동 → 폰 카메라로 모니터의 컨베이어 페이지 촬영 → OCR → Supabase 저장 → 질문하면 관련 지문을 찾아 Gemini가 한국어로 답변.

## 폴더 구조

```
ocr-rag-project/
├── README.md               이 문서
├── docker-compose.yml      세 컨테이너 정의 (api, worker, rag)
├── .env.example            환경변수 양식 → .env로 복사해서 사용
├── .gitignore
├── docs/
│   ├── project-plan.md     전체 계획서 (확정 사항, 담당별 할 일, 일정) — Notion용
│   └── prompts/            담당별 LLM 프롬프트 (A, B, C)
├── shared/                 공통 모듈: Supabase 클라이언트, 임베딩 함수
├── demo/                   컨베이어 페이지 + 정답 원문 passages.json (100개)
├── scripts/                passages.json 추출 스크립트
├── models/                 모델 캐시 (실행하면 자동으로 채워짐, Git 제외)
├── api/                    A 담당 — 프롬프트로 생성 예정
├── worker/                 B 담당 — 완성됨 (worker/README.md 참고)
└── rag/                    C 담당 — 프롬프트로 생성 예정
```

## 담당

| 담당 | 폴더 | 상태 | 시작 방법 |
|---|---|---|---|
| A | `api/` | 생성 예정 | `docs/prompts/prompt-A-api.md`를 LLM에 붙여넣기 |
| B | `worker/` | 완성 | `worker/README.md`의 테스트 순서대로 실행 |
| C (리드) | `rag/` + Supabase | 생성 예정 | Supabase 세팅 후 `docs/prompts/prompt-C-rag.md`의 rag 부분 생성 |

## 시작하기

1. 리드가 Supabase 세팅 (`docs/project-plan.md`의 "Supabase 세팅" SQL 실행, `uploads` 버킷 생성)
2. `.env.example`을 `.env`로 복사해서 값 채우기 (키는 메신저로 따로 공유)
3. 자기 컨테이너만 빌드·실행
   ```bash
   docker compose up --build api      # A
   docker compose up --build worker   # B
   docker compose up --build rag      # C
   ```
4. 통합할 때는 `docker compose up --build`

## 개발용 스위치 (.env)

| 변수 | 효과 | 쓰는 때 |
|---|---|---|
| `OCR_ENGINE=fake` | worker가 OCR 대신 정답 원문을 순서대로 사용 | PaddleOCR 준비 전 |
| `OCR_ENGINE=gemini` | Gemini로 글자 추출 | PaddleOCR Plan B |
| `RAG_MOCK=1` | api가 rag 대신 고정 응답 사용 | rag 준비 전 A 화면 개발 |
| `RAG_FAKE=1` | rag가 Gemini 없이 검색 결과만 반환 | Gemini 연결 전 |

실제 시연 전에는 `OCR_ENGINE=paddle`(또는 gemini)로 두고 `RAG_MOCK`, `RAG_FAKE`는 비워둡니다.
