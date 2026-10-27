# rag (C 담당)

`docs/prompts/prompt-C-rag.md`를 LLM에 붙여넣어 생성한 파일을 이 폴더에 둡니다.

만들어질 파일: `Dockerfile`, `requirements.txt`, `main.py`, `seed.py`

참고: C 프롬프트의 "내 작업 1: 공통 세팅"(docker-compose.yml, .env.example, .gitignore, shared/, passages.json 추출)은
이 프로젝트에 이미 들어 있으므로 "내 작업 2: rag 컨테이너"만 생성하면 됩니다. `sql/schema.sql`은 docs/project-plan.md의 SQL을 사용하세요.
