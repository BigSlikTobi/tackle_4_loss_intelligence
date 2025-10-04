# Status Tracking System

## Overview

The knowledge extraction module now uses a dedicated `story_group_extraction_status` table to track extraction progress, handle retries, and detect failures.

## Status Values

| Status | Description |
|--------|-------------|
| `pending` | Not yet processed (or reset for reprocessing) |
| `processing` | Currently being extracted |
| `completed` | Successfully extracted topics and entities |
| `failed` | Extraction failed (with error message) |
| `partial` | Some data extracted but not complete |

## Key Features

### 1. **Automatic Status Tracking**
- Status automatically updates during extraction pipeline
- Tracks timestamps: `started_at`, `completed_at`, `last_attempt_at`
- Records counts: `topics_extracted`, `entities_extracted`

### 2. **Error Tracking**
- Stores error messages (truncated to 1000 chars)
- Increments `error_count` on each failure
- Prevents infinite retry loops

### 3. **Retry Logic**
```bash
# Retry failed extractions (max 3 errors)
python extract_knowledge_cli.py --retry-failed

# Retry with custom error threshold
python extract_knowledge_cli.py --retry-failed --max-errors 5
```

### 4. **Progress Monitoring**
```bash
# View detailed progress with status breakdown
python extract_knowledge_cli.py --progress
```

Output includes:
- Total groups
- Completed groups
- Failed groups (with retry hint)
- Partial groups
- Processing groups
- Average topics/entities per group

## Database Schema

```sql
CREATE TABLE story_group_extraction_status (
    story_group_id UUID PRIMARY KEY REFERENCES story_groups(id),
    status TEXT NOT NULL DEFAULT 'pending',
    topics_extracted INT DEFAULT 0,
    entities_extracted INT DEFAULT 0,
    error_message TEXT,
    error_count INT DEFAULT 0,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    last_attempt_at TIMESTAMPTZ,
    model_used TEXT
);
```

## Workflow

### Initial Extraction
1. Group status starts as NULL (never processed)
2. Pipeline marks as `processing` when started
3. Extraction runs
4. Status updates to `completed` (success) or `failed` (error)

### Retry Failed Extractions
1. Check `--retry-failed` flag
2. Find groups with `status='failed'` and `error_count <= max_errors`
3. Re-run extraction
4. Increment `error_count` if fails again
5. Stop retrying after `max_errors` threshold

### Reprocessing (Manual)
To reprocess a group:
```python
from src.functions.knowledge_extraction.core.db.knowledge_writer import KnowledgeWriter

writer = KnowledgeWriter()
writer.clear_group_knowledge(story_group_id)  # Resets status to 'pending'
```

## Benefits

### Before (Topic-Based Detection)
❌ No distinction between success/failure  
❌ Can't retry failed extractions  
❌ Can't track partial successes  
❌ No error history  

### After (Status-Based Tracking)
✅ Clear status for each group  
✅ Automatic retry with error limiting  
✅ Error messages stored for debugging  
✅ Tracks partial extractions  
✅ Prevents infinite retry loops  
✅ Better progress monitoring  

## CLI Examples

```bash
# Normal extraction (skips completed and failed)
python extract_knowledge_cli.py --limit 10

# Retry failed groups (max 3 errors each)
python extract_knowledge_cli.py --retry-failed --limit 5

# Retry with higher error tolerance
python extract_knowledge_cli.py --retry-failed --max-errors 10

# Check progress with status breakdown
python extract_knowledge_cli.py --progress

# Dry run with retry
python extract_knowledge_cli.py --dry-run --retry-failed --limit 2
```

## Monitoring Queries

### Check failed groups
```sql
SELECT 
    sg.id,
    sg.created_at,
    ses.error_count,
    ses.error_message,
    ses.last_attempt_at
FROM story_groups sg
JOIN story_group_extraction_status ses ON sg.id = ses.story_group_id
WHERE ses.status = 'failed'
ORDER BY ses.last_attempt_at DESC;
```

### Check groups stuck in processing
```sql
SELECT 
    sg.id,
    ses.started_at,
    EXTRACT(EPOCH FROM (NOW() - ses.started_at)) / 60 AS minutes_processing
FROM story_groups sg
JOIN story_group_extraction_status ses ON sg.id = ses.story_group_id
WHERE ses.status = 'processing'
    AND ses.started_at < NOW() - INTERVAL '30 minutes';
```

### Get success rate
```sql
SELECT 
    status,
    COUNT(*) as count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) as percentage
FROM story_group_extraction_status
GROUP BY status;
```

## Implementation Files

- **`knowledge_writer.py`**: Updates status during write operations
- **`story_reader.py`**: Filters groups by status, supports retry logic
- **`extraction_pipeline.py`**: Passes retry options to reader
- **`extract_knowledge_cli.py`**: CLI flags for retry and progress
- **`schema.sql`**: Database schema for status table
