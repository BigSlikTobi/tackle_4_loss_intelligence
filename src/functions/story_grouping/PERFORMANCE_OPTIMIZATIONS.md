# Story Grouping Performance Optimizations

## Problem
The story grouping pipeline was experiencing database query timeouts when processing large datasets (8000+ stories). Queries were timing out on:

1. **`story_groups` queries** - Fetching active groups filtered by `created_at >= cutoff_date`
2. **`story_embeddings` queries** - Fetching ungrouped embeddings with date filters
3. **Large vector column scans** - Fetching centroid embeddings unnecessarily

## Solutions Implemented

### 1. Database Index Optimizations
**File**: `migrations/002_optimize_queries.sql`

Added composite indexes to speed up common query patterns:

- `idx_story_groups_status_created_at` - For filtering active groups by date
- `idx_story_embeddings_created_at` - For chronological filtering
- `idx_story_embeddings_news_url_id` - For JOIN operations with `story_group_members`
- `idx_story_embeddings_created_at_news_url_id` - Composite for date + ungrouped queries
- `idx_story_embeddings_with_vectors` - Partial index for stories with embeddings

**To apply**:
```bash
# Copy the SQL content from migrations/002_optimize_queries.sql
# and run it in your Supabase SQL Editor
```

### 2. Code Optimizations

#### `group_writer.py` - Optimized `get_active_groups()`
**Changes**:
- Check count first to estimate data size
- Use smaller batch size (500 instead of 1000)
- Remove `ORDER BY` clause that slows queries
- Add timeout handling with partial results
- Add max batches limit (20) as safety mechanism

**New methods**:
- `get_active_group_ids()` - Fetch only IDs without heavy centroid vectors
- `get_groups_by_ids()` - Fetch full data for specific groups

#### `embedding_reader.py` - Optimized `_iter_ungrouped_fallback_batches()`
**Changes**:
- Reduced batch sizes (500 instead of 1000)
- Added safety limits on grouped ID fetching (15 batches max)
- Reduced max batches to check (5-15 based on limit)
- Removed `ORDER BY` from embedding queries
- Better timeout handling with partial results
- More informative progress logging

## Performance Impact

### Before Optimization
```
# Typical timeout scenario:
- Fetching 8141 grouped story IDs: ~30 seconds
- Query story_embeddings with date filter: TIMEOUT (>15 seconds)
- Query story_groups with date filter: TIMEOUT (>15 seconds)
- Result: Pipeline fails
```

### After Optimization
```
# Expected improved performance:
- Database indexes enable efficient filtering
- Smaller batch sizes prevent timeouts
- Partial results returned even on timeout
- Pipeline can process data incrementally
```

## Usage

### Running the Migration
1. Open your Supabase dashboard
2. Go to SQL Editor
3. Copy content from `migrations/002_optimize_queries.sql`
4. Execute the SQL
5. Verify indexes were created:
   ```sql
   SELECT indexname, indexdef 
   FROM pg_indexes 
   WHERE tablename IN ('story_groups', 'story_embeddings')
   ORDER BY tablename, indexname;
   ```

### Using the Optimized Code
The code optimizations are transparent - no changes needed to CLI usage:

```bash
# Same usage as before
cd src/functions/story_grouping
python scripts/group_stories_cli.py --threshold 0.8 --days 14
```

### Monitoring Performance
Enable debug logging to see detailed batch processing:
```bash
export LOG_LEVEL=DEBUG
python scripts/group_stories_cli.py --threshold 0.8 --days 14
```

Watch for these log messages:
- `"Fetched batch X: Y groups (total: Z)"` - Progress through groups
- `"Found X already grouped stories"` - Grouped IDs collected
- `"Fetching embeddings batch at offset X (batch Y/Z)"` - Embeddings progress
- `"Timeout at offset X, returning Y items"` - Graceful degradation

## Testing the Optimizations

### Test Database Performance
```sql
-- Test 1: Active groups query (should be fast with new index)
EXPLAIN ANALYZE
SELECT id, member_count, created_at
FROM story_groups
WHERE status = 'active' 
  AND created_at >= NOW() - INTERVAL '14 days'
LIMIT 500;

-- Test 2: Ungrouped embeddings query (should use partial index)
EXPLAIN ANALYZE
SELECT se.id, se.news_url_id, se.created_at
FROM story_embeddings se
LEFT JOIN story_group_members sgm ON se.news_url_id = sgm.news_url_id
WHERE se.embedding_vector IS NOT NULL
  AND se.created_at >= NOW() - INTERVAL '14 days'
  AND sgm.news_url_id IS NULL
LIMIT 100;
```

Look for "Index Scan" or "Index Only Scan" in the EXPLAIN output.

### Test CLI with Small Dataset
```bash
# Test with limited processing to verify it doesn't timeout
python scripts/group_stories_cli.py --threshold 0.8 --days 7
```

## Troubleshooting

### Still Experiencing Timeouts?

1. **Check if indexes were created**:
   ```sql
   SELECT indexname FROM pg_indexes 
   WHERE tablename IN ('story_groups', 'story_embeddings');
   ```

2. **Reduce days_lookback parameter**:
   ```bash
   # Try fewer days to reduce dataset size
   python scripts/group_stories_cli.py --threshold 0.8 --days 7
   ```

3. **Check Supabase connection limits**:
   - Verify your plan allows sufficient connection time
   - Consider upgrading plan if on free tier

4. **Review query plans**:
   ```sql
   -- If queries still slow, check what indexes are being used
   EXPLAIN (ANALYZE, BUFFERS)
   SELECT * FROM story_groups 
   WHERE status = 'active' 
     AND created_at >= NOW() - INTERVAL '14 days';
   ```

### Partial Results Warning
If you see: `"Timeout at offset X, returning Y items"`

This is **expected behavior** - the code returns partial results gracefully. The pipeline will:
- Process what it collected
- Group available stories
- Complete successfully with partial data

To process more data, run the command again - it will pick up where it left off.

## Future Optimizations

If timeouts persist with large datasets:

1. **Add database-level stored procedures** to reduce network roundtrips
2. **Implement time-windowed processing** - process data in smaller date ranges
3. **Add caching layer** for frequently accessed group data
4. **Use materialized views** for expensive aggregations
5. **Consider async batch processing** for very large datasets

## Rollback

If issues occur, drop the new indexes:
```sql
DROP INDEX IF EXISTS idx_story_groups_status_created_at;
DROP INDEX IF EXISTS idx_story_embeddings_created_at;
DROP INDEX IF EXISTS idx_story_embeddings_news_url_id;
DROP INDEX IF EXISTS idx_story_embeddings_created_at_news_url_id;
DROP INDEX IF EXISTS idx_story_embeddings_with_vectors;
```

Code changes are backward compatible - no rollback needed.
