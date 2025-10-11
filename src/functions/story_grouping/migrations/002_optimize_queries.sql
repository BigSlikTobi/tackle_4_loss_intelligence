-- Migration: Optimize Story Grouping Queries
-- Date: 2025-10-11
-- Purpose: Add composite indexes to prevent query timeouts on large datasets

-- =============================================================================
-- Problem Analysis
-- =============================================================================
-- Current issues causing timeouts:
-- 1. story_groups queries with status='active' AND created_at >= cutoff_date
--    - Existing indexes are separate (status only, created_at only)
--    - Query planner can't efficiently use both filters
--
-- 2. story_embeddings queries with created_at >= cutoff_date AND embedding_vector IS NOT NULL
--    - No index on created_at for story_embeddings
--    - Scanning large vector columns is slow
--
-- 3. LEFT JOIN between story_embeddings and story_group_members on news_url_id
--    - No index on story_embeddings(news_url_id) for efficient joins
--
-- =============================================================================
-- Solution: Composite and Missing Indexes
-- =============================================================================

-- Index 1: Composite index for story_groups status + created_at queries
-- This covers: WHERE status = 'active' AND created_at >= cutoff_date
DROP INDEX IF EXISTS idx_story_groups_status_created_at;
CREATE INDEX idx_story_groups_status_created_at 
ON story_groups(status, created_at DESC);

COMMENT ON INDEX idx_story_groups_status_created_at IS 
'Composite index for filtering active groups within a date range';

-- Index 2: Index on story_embeddings created_at for date filtering
-- This speeds up: WHERE created_at >= cutoff_date
DROP INDEX IF EXISTS idx_story_embeddings_created_at;
CREATE INDEX idx_story_embeddings_created_at 
ON story_embeddings(created_at DESC);

COMMENT ON INDEX idx_story_embeddings_created_at IS 
'Index for chronological filtering of story embeddings';

-- Index 3: Index on story_embeddings news_url_id for JOINs
-- This speeds up: LEFT JOIN story_group_members ON news_url_id
-- Note: This is crucial because the join happens frequently in ungrouped queries
DROP INDEX IF EXISTS idx_story_embeddings_news_url_id;
CREATE INDEX idx_story_embeddings_news_url_id 
ON story_embeddings(news_url_id);

COMMENT ON INDEX idx_story_embeddings_news_url_id IS 
'Index for joining story_embeddings with story_group_members';

-- Index 4: Composite index for story_embeddings date + news_url_id
-- This covers: WHERE created_at >= cutoff AND NOT EXISTS (subquery on news_url_id)
DROP INDEX IF EXISTS idx_story_embeddings_created_at_news_url_id;
CREATE INDEX idx_story_embeddings_created_at_news_url_id 
ON story_embeddings(created_at DESC, news_url_id);

COMMENT ON INDEX idx_story_embeddings_created_at_news_url_id IS 
'Composite index for date-filtered ungrouped story queries';

-- Index 5: Partial index for story_embeddings with non-null vectors
-- This is more selective and only indexes rows we actually care about
DROP INDEX IF EXISTS idx_story_embeddings_with_vectors;
CREATE INDEX idx_story_embeddings_with_vectors 
ON story_embeddings(created_at DESC, news_url_id) 
WHERE embedding_vector IS NOT NULL;

COMMENT ON INDEX idx_story_embeddings_with_vectors IS 
'Partial index for stories with embeddings, optimized for ungrouped queries';

-- =============================================================================
-- Verification Queries
-- =============================================================================
-- Run these after migration to verify performance improvement

-- Test 1: Active groups in date range (should use idx_story_groups_status_created_at)
-- EXPLAIN ANALYZE
-- SELECT id, member_count, created_at
-- FROM story_groups
-- WHERE status = 'active' 
--   AND created_at >= NOW() - INTERVAL '14 days'
-- ORDER BY created_at DESC;

-- Test 2: Ungrouped embeddings (should use idx_story_embeddings_with_vectors)
-- EXPLAIN ANALYZE
-- SELECT se.id, se.news_url_id, se.created_at
-- FROM story_embeddings se
-- LEFT JOIN story_group_members sgm ON se.news_url_id = sgm.news_url_id
-- WHERE se.embedding_vector IS NOT NULL
--   AND se.created_at >= NOW() - INTERVAL '14 days'
--   AND sgm.news_url_id IS NULL
-- LIMIT 100;

-- Test 3: Check index usage
-- SELECT 
--     schemaname,
--     tablename,
--     indexname,
--     idx_scan as index_scans,
--     idx_tup_read as tuples_read,
--     idx_tup_fetch as tuples_fetched
-- FROM pg_stat_user_indexes
-- WHERE schemaname = 'public'
--   AND (tablename = 'story_groups' OR tablename = 'story_embeddings')
-- ORDER BY tablename, indexname;

-- =============================================================================
-- Cleanup (Optional)
-- =============================================================================
-- After verifying new indexes work, consider dropping old single-column indexes
-- if they're no longer used:
-- 
-- DROP INDEX IF EXISTS idx_story_groups_status;
-- DROP INDEX IF EXISTS idx_story_groups_created_at;
-- 
-- Note: Keep them for now until we verify query patterns in production
