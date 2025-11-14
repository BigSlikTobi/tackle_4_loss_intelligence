-- Schema changes for the content_summarization module.

-- 1.1 Extend news_urls with processing timestamps.
ALTER TABLE news_urls
    ADD COLUMN IF NOT EXISTS content_extracted_at TIMESTAMPTZ NULL;
ALTER TABLE news_urls
    ADD COLUMN IF NOT EXISTS facts_extracted_at TIMESTAMPTZ NULL;
ALTER TABLE news_urls
    ADD COLUMN IF NOT EXISTS summary_created_at TIMESTAMPTZ NULL;

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
