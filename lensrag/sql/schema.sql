-- Supabase SQL Editor에 통째로 붙여넣어 한 번 실행하세요.
-- 실행 후 Storage에서 `uploads` 버킷(private)을 따로 만들어야 합니다.

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
  image_path text,                -- Storage 버킷 uploads 안의 경로 ({uuid}.jpg)
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

-- 새 테이블에 API 역할 권한이 자동으로 붙지 않는 프로젝트라서 직접 부여.
-- 세 컨테이너 모두 service_role 키만 쓰므로 anon/authenticated에는 주지 않음.
grant select, insert, update, delete on sessions, passages to service_role;
grant usage, select on all sequences in schema public to service_role;
grant execute on function match_passages(vector, int) to service_role;
