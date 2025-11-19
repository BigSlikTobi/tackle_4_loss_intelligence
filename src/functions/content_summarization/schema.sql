-- Schema changes for the content_summarization module.

-- 1.1 Extend news_urls with processing timestamps.
ALTER TABLE news_urls
    ADD COLUMN IF NOT EXISTS content_extracted_at TIMESTAMPTZ NULL;
ALTER TABLE news_urls
    ADD COLUMN IF NOT EXISTS facts_extracted_at TIMESTAMPTZ NULL;
ALTER TABLE news_urls
    ADD COLUMN IF NOT EXISTS summary_created_at TIMESTAMPTZ NULL;
ALTER TABLE news_urls
    ADD COLUMN IF NOT EXISTS knowledge_extracted_at TIMESTAMPTZ NULL;
ALTER TABLE news_urls
    ADD COLUMN IF NOT EXISTS facts_count INTEGER;
ALTER TABLE news_urls
    ADD COLUMN IF NOT EXISTS distinct_topics INTEGER;
ALTER TABLE news_urls
    ADD COLUMN IF NOT EXISTS distinct_teams INTEGER;
ALTER TABLE news_urls
    ADD COLUMN IF NOT EXISTS article_difficulty TEXT;

-- 1.2 Create news_facts table for atomic article facts.
CREATE TABLE IF NOT EXISTS news_facts (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    news_url_id UUID NOT NULL REFERENCES news_urls(id) ON DELETE CASCADE,
    fact_text TEXT NOT NULL,
    llm_model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_news_facts_news_url_id
    ON news_facts (news_url_id);

-- 1.3 Topic-level summaries for hard articles.
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

-- 1.4 Ensure context_summaries schema has required columns.
ALTER TABLE context_summaries
    ADD COLUMN IF NOT EXISTS id UUID DEFAULT gen_random_uuid();
ALTER TABLE context_summaries
    ADD COLUMN IF NOT EXISTS news_url_id UUID NOT NULL REFERENCES news_urls(id) ON DELETE CASCADE;
ALTER TABLE context_summaries
    ADD COLUMN IF NOT EXISTS summary_text TEXT NOT NULL;
ALTER TABLE context_summaries
    ADD COLUMN IF NOT EXISTS llm_model TEXT NOT NULL;
ALTER TABLE context_summaries
    ADD COLUMN IF NOT EXISTS prompt_version TEXT NOT NULL;
ALTER TABLE context_summaries
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'context_summaries_pkey'
    ) THEN
        ALTER TABLE context_summaries
            ADD CONSTRAINT context_summaries_pkey PRIMARY KEY (id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_context_summaries_news_url_id
    ON context_summaries (news_url_id);
