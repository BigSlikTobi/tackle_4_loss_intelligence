-- Fix constraints on story_embeddings to allow multiple embeddings per article (e.g. per topic)
-- We need to drop any unique constraints that limit us to one embedding per news_url_id or (news_url_id, model_name)

DO $$
BEGIN
    -- Drop the constraint that limits one embedding per URL (if it exists)
    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'story_embeddings_news_url_id_key'
    ) THEN
        ALTER TABLE story_embeddings DROP CONSTRAINT story_embeddings_news_url_id_key;
    END IF;

    -- Drop the constraint that limits one embedding per URL+Model (if it exists)
    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ux_story_embeddings_url_model'
    ) THEN
        ALTER TABLE story_embeddings DROP CONSTRAINT ux_story_embeddings_url_model;
    END IF;
END $$;
