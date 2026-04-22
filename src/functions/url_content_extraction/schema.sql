-- Ephemeral handoff table for the URL content extraction service.
--
-- The extractor writes one row per processed URL. Downstream consumers
-- (e.g. facts_batch.request_generator) read the row to avoid a second
-- Playwright fetch, then mark `consumed_at` once their work is durable.
-- A sweep CLI (`scripts/ephemeral_sweep_cli.py`) deletes rows where
-- `consumed_at IS NOT NULL OR expires_at < now()`.
--
-- Apply via the repo's standard Supabase migration path.

create table if not exists news_url_content_ephemeral (
    id            uuid primary key default gen_random_uuid(),
    news_url_id   uuid not null unique,
    content       text not null,
    title         text,
    paragraphs    jsonb,
    metadata      jsonb,
    extracted_at  timestamptz not null default now(),
    consumed_at   timestamptz,
    expires_at    timestamptz not null default (now() + interval '48 hours')
);

create index if not exists idx_nuce_expires_at
    on news_url_content_ephemeral (expires_at);
create index if not exists idx_nuce_consumed_at
    on news_url_content_ephemeral (consumed_at);
