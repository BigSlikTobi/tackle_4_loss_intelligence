-- Knowledge Extraction Database Schema (Fact-level)
-- -------------------------------------------------
-- Stores per-fact topics and entities extracted from news articles.

-- =============================================================================
-- news_fact_topics
-- =============================================================================
CREATE TABLE IF NOT EXISTS news_fact_topics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    news_fact_id UUID NOT NULL REFERENCES news_facts(id) ON DELETE CASCADE,
    topic TEXT NOT NULL,
    canonical_topic TEXT NOT NULL,
    confidence REAL,
    rank INTEGER,
    is_primary BOOLEAN DEFAULT FALSE,
    llm_model TEXT,
    prompt_version TEXT,
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT news_fact_topics_unique UNIQUE (news_fact_id, canonical_topic)
);

CREATE INDEX IF NOT EXISTS idx_news_fact_topics_fact_id
ON news_fact_topics(news_fact_id);

CREATE INDEX IF NOT EXISTS idx_news_fact_topics_canonical
ON news_fact_topics(canonical_topic);

COMMENT ON TABLE news_fact_topics IS
'Topics extracted per fact to support downstream grouping and classification';

-- =============================================================================
-- news_fact_entities
-- =============================================================================
CREATE TABLE IF NOT EXISTS news_fact_entities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    news_fact_id UUID NOT NULL REFERENCES news_facts(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('player', 'team', 'game')),
    entity_id TEXT,
    entity_dedup_key TEXT NOT NULL,
    mention_text TEXT,
    matched_name TEXT,
    confidence REAL,
    is_primary BOOLEAN DEFAULT FALSE,
    rank INTEGER,
    position TEXT,
    team_abbr TEXT,
    team_name TEXT,
    llm_model TEXT,
    prompt_version TEXT,
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT news_fact_entities_unique UNIQUE (news_fact_id, entity_type, entity_dedup_key)
);

CREATE INDEX IF NOT EXISTS idx_news_fact_entities_fact_id
ON news_fact_entities(news_fact_id);

CREATE INDEX IF NOT EXISTS idx_news_fact_entities_type_id
ON news_fact_entities(entity_type, entity_id);

CREATE INDEX IF NOT EXISTS idx_news_fact_entities_team_abbr
ON news_fact_entities(team_abbr) WHERE team_abbr IS NOT NULL;

COMMENT ON TABLE news_fact_entities IS
'Resolved entities extracted per fact for accurate team/player tracking';

-- =============================================================================
-- Knowledge extraction status helpers
-- =============================================================================
ALTER TABLE news_urls
    ADD COLUMN IF NOT EXISTS knowledge_extracted_at TIMESTAMPTZ NULL;

ALTER TABLE news_urls
    ADD COLUMN IF NOT EXISTS knowledge_error_count INTEGER DEFAULT 0;

COMMENT ON COLUMN news_urls.knowledge_extracted_at IS
'Timestamp when knowledge extraction (topics/entities) was completed for this URL';

COMMENT ON COLUMN news_urls.knowledge_error_count IS
'Number of consecutive knowledge extraction failures for this URL';
