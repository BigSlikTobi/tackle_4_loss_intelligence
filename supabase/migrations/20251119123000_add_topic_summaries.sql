CREATE TABLE IF NOT EXISTS topic_summaries (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    news_url_id UUID NOT NULL REFERENCES news_urls(id) ON DELETE CASCADE,
    primary_topic TEXT NOT NULL,
    primary_team TEXT,
    primary_scope_type TEXT,
    primary_scope_id TEXT,
    primary_scope_label TEXT,
    summary_text TEXT NOT NULL,
    llm_model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_topic_summaries_news_url_id
    ON topic_summaries (news_url_id);

CREATE INDEX IF NOT EXISTS idx_topic_summaries_topic_team
    ON topic_summaries (primary_topic, COALESCE(primary_team, ''));

CREATE INDEX IF NOT EXISTS idx_topic_summaries_scope
    ON topic_summaries (primary_scope_type, COALESCE(primary_scope_id, ''));
