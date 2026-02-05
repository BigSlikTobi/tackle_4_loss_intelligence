-- Image Selection Database Schema
-- 
-- This file contains database schema changes required for the image_selection module.
-- Run this migration against your Supabase database to enable image deduplication.

--------------------------------------------------------------------------------
-- Add unique constraint on original_url to prevent duplicate image records
-- This enables upsert operations and prevents race conditions during concurrent uploads
--------------------------------------------------------------------------------

-- First, handle any existing duplicates by keeping only the first record for each original_url
-- This creates a temp table with the ids to keep
CREATE TEMP TABLE ids_to_keep AS
SELECT DISTINCT ON (original_url) id
FROM content.article_images
WHERE original_url IS NOT NULL
ORDER BY original_url, created_at ASC NULLS LAST, id ASC;

-- Delete duplicate rows (keeping the earliest ones)
DELETE FROM content.article_images
WHERE original_url IS NOT NULL
  AND id NOT IN (SELECT id FROM ids_to_keep);

DROP TABLE ids_to_keep;

-- Now add the unique index on original_url
-- Using a partial index to exclude NULL values (which are allowed to be duplicated)
CREATE UNIQUE INDEX IF NOT EXISTS idx_article_images_original_url_unique
ON content.article_images (original_url)
WHERE original_url IS NOT NULL;

-- Also add a regular index for faster lookups
CREATE INDEX IF NOT EXISTS idx_article_images_original_url
ON content.article_images (original_url);
