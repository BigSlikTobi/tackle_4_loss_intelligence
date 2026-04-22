-- Ephemeral job store for the article knowledge extraction service.
--
-- Jobs are short-lived: callers submit, poll, then retrieve. The row is
-- deleted atomically on the first terminal poll (delete-on-read), and any
-- rows past `expires_at` are pruned by a cron-driven cleanup CLI.
--
-- Apply via the repo's standard Supabase migration path.

create table if not exists article_knowledge_extraction_jobs (
    job_id       uuid primary key default gen_random_uuid(),
    status       text not null check (status in ('queued','running','succeeded','failed')),
    input        jsonb not null,
    result       jsonb,
    error        jsonb,
    attempts     int  not null default 0,
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now(),
    started_at   timestamptz,
    finished_at  timestamptz,
    expires_at   timestamptz not null default (now() + interval '24 hours')
);

create index if not exists idx_akej_status_created
    on article_knowledge_extraction_jobs (status, created_at);
create index if not exists idx_akej_expires_at
    on article_knowledge_extraction_jobs (expires_at);

-- Atomic consume-on-read: returns the row if terminal and deletes it in the
-- same transaction. Returns an empty row set if the job is still non-terminal
-- or does not exist.
create or replace function consume_article_knowledge_job(p_job_id uuid)
returns setof article_knowledge_extraction_jobs
language sql
volatile
as $$
    with d as (
        delete from article_knowledge_extraction_jobs
        where job_id = p_job_id
          and status in ('succeeded', 'failed')
        returning *
    )
    select * from d;
$$;
