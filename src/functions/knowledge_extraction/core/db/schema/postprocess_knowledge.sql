-- Post-process knowledge extraction results.
-- Updates knowledge_extracted_at, facts_count, and article_difficulty based on existing data.
--
-- Run this against the Supabase/Postgres database after batch processing completes.
-- Example:
--   psql "$DATABASE_URL" -f postprocess_knowledge.sql

WITH fact_counts AS (
    SELECT
        news_url_id,
        COUNT(*) AS fact_count
    FROM news_facts
    GROUP BY news_url_id
),
latest_topics AS (
    SELECT
        nf.news_url_id,
        MAX(nft.extracted_at) AS latest_topic_at
    FROM news_facts nf
    JOIN news_fact_topics nft ON nft.news_fact_id = nf.id
    GROUP BY nf.news_url_id
),
latest_entities AS (
    SELECT
        nf.news_url_id,
        MAX(nfe.extracted_at) AS latest_entity_at
    FROM news_facts nf
    JOIN news_fact_entities nfe ON nfe.news_fact_id = nf.id
    GROUP BY nf.news_url_id
),
combined AS (
    SELECT
        COALESCE(fc.news_url_id, lt.news_url_id, le.news_url_id) AS news_url_id,
        COALESCE(fc.fact_count, 0) AS fact_count,
        lt.latest_topic_at,
        le.latest_entity_at
    FROM fact_counts fc
    FULL OUTER JOIN latest_topics lt ON lt.news_url_id = fc.news_url_id
    FULL OUTER JOIN latest_entities le ON le.news_url_id = COALESCE(fc.news_url_id, lt.news_url_id)
)
UPDATE news_urls AS nu
SET
    knowledge_extracted_at = CASE
        WHEN c.latest_topic_at IS NULL AND c.latest_entity_at IS NULL THEN NULL
        ELSE GREATEST(COALESCE(c.latest_topic_at, c.latest_entity_at), COALESCE(c.latest_entity_at, c.latest_topic_at))
    END,
    facts_count = c.fact_count,
    article_difficulty = CASE
        WHEN c.fact_count <= 5 THEN 'easy'
        WHEN c.fact_count <= 15 THEN 'medium'
        ELSE 'hard'
    END
FROM combined c
WHERE nu.id = c.news_url_id;
