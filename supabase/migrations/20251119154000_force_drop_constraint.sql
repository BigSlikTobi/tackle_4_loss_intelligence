-- Attempt to drop the unique constraint or index 'ux_story_embeddings_url_model'
-- to allow multiple embeddings per article/model (e.g. for different topics).

-- 1. Try dropping as a unique index (if created via CREATE UNIQUE INDEX)
DROP INDEX IF EXISTS ux_story_embeddings_url_model;

-- 2. Try dropping as a table constraint (if created via ALTER TABLE ADD CONSTRAINT)
ALTER TABLE story_embeddings DROP CONSTRAINT IF EXISTS ux_story_embeddings_url_model;
