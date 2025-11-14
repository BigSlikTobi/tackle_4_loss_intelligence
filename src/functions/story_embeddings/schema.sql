-- Schema changes for the story_embeddings module.

-- 1.3 Create facts_embeddings table for per-fact vectors.
CREATE TABLE IF NOT EXISTS facts_embeddings (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    news_fact_id BIGINT NOT NULL REFERENCES news_facts(id) ON DELETE CASCADE,
    embedding_vector VECTOR NOT NULL,
    model_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_facts_embeddings_fact_id
    ON facts_embeddings (news_fact_id);

CREATE INDEX IF NOT EXISTS idx_facts_embeddings_vector
    ON facts_embeddings
    USING ivfflat (embedding_vector vector_cosine_ops)
    WITH (lists = 100);

-- 1.5 Ensure story_embeddings table has required columns and indexes.
ALTER TABLE story_embeddings
    ADD COLUMN IF NOT EXISTS id BIGINT GENERATED ALWAYS AS IDENTITY;
ALTER TABLE story_embeddings
    ADD COLUMN IF NOT EXISTS news_url_id BIGINT NOT NULL REFERENCES news_urls(id) ON DELETE CASCADE;
ALTER TABLE story_embeddings
    ADD COLUMN IF NOT EXISTS embedding_vector VECTOR NOT NULL;
ALTER TABLE story_embeddings
    ADD COLUMN IF NOT EXISTS model_name TEXT NOT NULL;
ALTER TABLE story_embeddings
    ADD COLUMN IF NOT EXISTS embedding_type TEXT NOT NULL;
ALTER TABLE story_embeddings
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'story_embeddings_pkey'
    ) THEN
        ALTER TABLE story_embeddings
            ADD CONSTRAINT story_embeddings_pkey PRIMARY KEY (id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_story_embeddings_url_type
    ON story_embeddings (news_url_id, embedding_type);

CREATE INDEX IF NOT EXISTS idx_story_embeddings_vector
    ON story_embeddings
    USING ivfflat (embedding_vector vector_cosine_ops)
    WITH (lists = 100);
