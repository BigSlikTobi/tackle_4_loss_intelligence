-- Story Grouping Database Schema
-- 
-- This schema defines tables for clustering similar stories based on
-- embedding vectors. Stories are grouped using cosine similarity and
-- centroid-based clustering.

-- Enable the pgvector extension if not already enabled
-- (Run this in your Supabase SQL Editor if needed)
-- CREATE EXTENSION IF NOT EXISTS vector;

-- =============================================================================
-- story_groups
-- =============================================================================
-- Stores metadata and centroid embeddings for story groups.
-- Each group represents a cluster of similar stories.

CREATE TABLE IF NOT EXISTS story_groups (
    -- Unique identifier for the group
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Centroid embedding vector (mean of all member embeddings)
    -- Dimension should match embedding model (1536 for text-embedding-3-small)
    centroid_embedding vector(1536) NOT NULL,
    
    -- Number of stories in this group
    -- Useful for quickly assessing group size without counting members
    member_count INTEGER NOT NULL DEFAULT 0,
    
    -- Group status for lifecycle management
    -- Possible values: 'active', 'archived', 'merged'
    status TEXT NOT NULL DEFAULT 'active',
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Add index on status for efficient filtering of active groups
CREATE INDEX IF NOT EXISTS idx_story_groups_status 
ON story_groups(status);

-- Add index on created_at for chronological queries
CREATE INDEX IF NOT EXISTS idx_story_groups_created_at 
ON story_groups(created_at DESC);

-- Add vector similarity index for efficient nearest neighbor search
-- This uses HNSW (Hierarchical Navigable Small World) algorithm
CREATE INDEX IF NOT EXISTS idx_story_groups_centroid_embedding 
ON story_groups USING hnsw (centroid_embedding vector_cosine_ops);

-- Add comment for documentation
COMMENT ON TABLE story_groups IS 
'Groups of similar stories clustered by embedding similarity';

COMMENT ON COLUMN story_groups.centroid_embedding IS 
'Normalized mean of all member embedding vectors';

COMMENT ON COLUMN story_groups.member_count IS 
'Number of stories in group (denormalized for performance)';

COMMENT ON COLUMN story_groups.status IS 
'Lifecycle status: active, archived, or merged';


-- =============================================================================
-- story_group_members
-- =============================================================================
-- Maps news URLs to story groups with similarity scores.
-- This is a many-to-one relationship: each story belongs to one group.

CREATE TABLE IF NOT EXISTS story_group_members (
    -- Unique identifier for the membership record
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Foreign key to story_groups
    group_id UUID NOT NULL REFERENCES story_groups(id) ON DELETE CASCADE,
    
    -- Foreign key to news_urls (from news_extraction module)
    news_url_id UUID NOT NULL REFERENCES news_urls(id) ON DELETE CASCADE,
    
    -- Cosine similarity score between story embedding and group centroid
    -- Range: 0.0 (completely dissimilar) to 1.0 (identical)
    similarity_score REAL NOT NULL,
    
    -- Timestamp when story was added to group
    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Ensure a story can only be in a group once
    CONSTRAINT story_group_members_unique UNIQUE (group_id, news_url_id)
);

-- Add index on group_id for efficient member lookups
CREATE INDEX IF NOT EXISTS idx_story_group_members_group_id 
ON story_group_members(group_id);

-- Add index on news_url_id for checking if a story is grouped
CREATE INDEX IF NOT EXISTS idx_story_group_members_news_url_id 
ON story_group_members(news_url_id);

-- Add index on similarity_score for quality analysis
CREATE INDEX IF NOT EXISTS idx_story_group_members_similarity_score 
ON story_group_members(similarity_score DESC);

-- Add comment for documentation
COMMENT ON TABLE story_group_members IS 
'Maps news URLs to story groups with similarity scores';

COMMENT ON COLUMN story_group_members.similarity_score IS 
'Cosine similarity with group centroid (0.0-1.0)';


-- =============================================================================
-- Triggers for maintaining updated_at timestamps
-- =============================================================================

-- Function to update the updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger for story_groups
DROP TRIGGER IF EXISTS update_story_groups_updated_at ON story_groups;
CREATE TRIGGER update_story_groups_updated_at
    BEFORE UPDATE ON story_groups
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();


-- =============================================================================
-- Helper Views
-- =============================================================================

-- View: group_summary
-- Provides quick overview of each group with member count and average similarity
CREATE OR REPLACE VIEW group_summary AS
SELECT 
    g.id,
    g.status,
    g.member_count,
    g.created_at,
    g.updated_at,
    COUNT(m.id) AS actual_member_count,
    AVG(m.similarity_score) AS avg_similarity,
    MIN(m.similarity_score) AS min_similarity,
    MAX(m.similarity_score) AS max_similarity
FROM story_groups g
LEFT JOIN story_group_members m ON g.id = m.group_id
GROUP BY g.id, g.status, g.member_count, g.created_at, g.updated_at
ORDER BY g.created_at DESC;

COMMENT ON VIEW group_summary IS 
'Summary statistics for each story group including member counts and similarity scores';


-- View: ungrouped_stories
-- Shows stories with embeddings that haven't been assigned to a group yet
CREATE OR REPLACE VIEW ungrouped_stories AS
SELECT 
    se.id,
    se.news_url_id,
    se.created_at
FROM story_embeddings se
WHERE se.embedding_vector IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 
    FROM story_group_members m 
    WHERE m.news_url_id = se.news_url_id
  )
ORDER BY se.created_at;

COMMENT ON VIEW ungrouped_stories IS 
'Stories with embeddings that have not been assigned to a group';


-- =============================================================================
-- Sample Queries
-- =============================================================================

-- Find the most similar group for a given embedding vector
-- (Replace the vector values with actual embedding)
/*
SELECT 
    id,
    status,
    member_count,
    1 - (centroid_embedding <=> '[0.1, 0.2, ...]'::vector) AS similarity
FROM story_groups
WHERE status = 'active'
ORDER BY centroid_embedding <=> '[0.1, 0.2, ...]'::vector
LIMIT 5;
*/

-- Get all members of a specific group with their similarity scores
/*
SELECT 
    m.news_url_id,
    m.similarity_score,
    m.added_at,
    nu.url,
    nu.title
FROM story_group_members m
JOIN news_urls nu ON m.news_url_id = nu.id
WHERE m.group_id = 'YOUR_GROUP_ID_HERE'
ORDER BY m.similarity_score DESC;
*/

-- Find groups with low average similarity (may need splitting)
/*
SELECT 
    g.id,
    g.member_count,
    AVG(m.similarity_score) AS avg_similarity
FROM story_groups g
JOIN story_group_member m ON g.id = m.group_id
WHERE g.status = 'active'
GROUP BY g.id, g.member_count
HAVING AVG(m.similarity_score) < 0.75
ORDER BY avg_similarity;
*/

-- Get grouping statistics
/*
SELECT 
    COUNT(DISTINCT g.id) AS total_groups,
    COUNT(DISTINCT m.news_url_id) AS grouped_stories,
    AVG(g.member_count) AS avg_group_size,
    MIN(g.member_count) AS min_group_size,
    MAX(g.member_count) AS max_group_size
FROM story_groups g
LEFT JOIN story_group_members m ON g.id = m.group_id
WHERE g.status = 'active';
*/
