-- Migration: Create function to efficiently fetch ungrouped embeddings
-- This avoids the timeout issues by using a LEFT JOIN at the database level

-- Drop function if exists (for idempotency)
DROP FUNCTION IF EXISTS get_ungrouped_embeddings(INTEGER, INTEGER, TIMESTAMP WITH TIME ZONE);

-- Create the function
CREATE OR REPLACE FUNCTION get_ungrouped_embeddings(
    p_limit INTEGER DEFAULT 1000,
    p_offset INTEGER DEFAULT 0,
    p_cutoff_date TIMESTAMP WITH TIME ZONE DEFAULT NULL
)
RETURNS TABLE (
    id UUID,
    news_url_id UUID,
    embedding_vector vector(1536),
    created_at TIMESTAMP WITH TIME ZONE
)
LANGUAGE plpgsql
STABLE
AS $$
BEGIN
    RETURN QUERY
    SELECT DISTINCT
        se.id,
        se.news_url_id,
        se.embedding_vector,
        se.created_at
    FROM story_embeddings se
    LEFT JOIN story_group_members sgm ON se.news_url_id = sgm.news_url_id
    WHERE se.embedding_vector IS NOT NULL
      AND sgm.news_url_id IS NULL
      AND (p_cutoff_date IS NULL OR se.created_at >= p_cutoff_date)
    ORDER BY se.created_at ASC
    LIMIT p_limit
    OFFSET p_offset;
END;
$$;

-- Grant execute permission to authenticated users
GRANT EXECUTE ON FUNCTION get_ungrouped_embeddings(INTEGER, INTEGER, TIMESTAMP WITH TIME ZONE) TO authenticated;
GRANT EXECUTE ON FUNCTION get_ungrouped_embeddings(INTEGER, INTEGER, TIMESTAMP WITH TIME ZONE) TO anon;

-- Add comment for documentation
COMMENT ON FUNCTION get_ungrouped_embeddings IS 
'Efficiently fetches story embeddings that are not yet assigned to any group. 
Uses LEFT JOIN to filter at database level and supports date filtering.
Parameters:
  - p_limit: Maximum number of rows to return (default: 1000)
  - p_offset: Number of rows to skip (default: 0)
  - p_cutoff_date: Only return embeddings created after this date (default: NULL for no filter)';
