# Batch Creation Timeout Protection

This document describes the timeout protection mechanisms added to prevent batch creation processes from hanging indefinitely and blocking the content pipeline.

## Problem

Batch creation (not OpenAI processing) can hang during:
1. **Content fetching** - parallel fetching from slow/unresponsive URLs
2. **OpenAI API calls** - file upload or batch creation network delays
3. **Database operations** - large queries or prefetching loops

When batch creation hangs:
- GitHub Actions workflow stays "running" for hours
- No batch is registered in tracking table
- Next workflow run sees no active batch and tries again
- Pipeline is blocked until manual intervention

**Observed**: Facts batch creation hung for 4 hours during content fetching phase.

---

## Solution Overview

Three-layer timeout protection:

### 1. Content Fetching Timeout (10 minutes)
**Location**: `src/functions/url_content_extraction/core/facts_batch/request_generator.py`

Wraps the `ThreadPoolExecutor` parallel content fetching with an overall timeout:
- **Individual URL timeout**: 45 seconds (existing)
- **Overall fetching timeout**: 600 seconds (10 minutes) - **NEW**
- Uses `as_completed(futures, timeout=600)` to cap total fetching time
- Gracefully handles timeouts - processes what was fetched successfully

```python
# Parallel content fetching with overall timeout protection
CONTENT_FETCH_TIMEOUT = 600  # 10 minutes max for all fetching

with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
    futures = {...}
    
    # Use as_completed with timeout to prevent indefinite hangs
    for future in as_completed(futures, timeout=CONTENT_FETCH_TIMEOUT):
        # Process results...
```

### 2. OpenAI API Timeouts (60s/30s)
**Location**: `src/functions/url_content_extraction/core/facts_batch/pipeline.py`

Wraps OpenAI SDK calls with timeout protection:
- **File upload**: 60 seconds
- **Batch creation**: 30 seconds

```python
# Upload to OpenAI with timeout protection
with ThreadPoolExecutor(max_workers=1) as executor:
    future = executor.submit(
        lambda: openai.files.create(file=..., purpose="batch")
    )
    try:
        uploaded = future.result(timeout=OPENAI_FILE_UPLOAD_TIMEOUT)
    except FuturesTimeoutError:
        raise TimeoutError("OpenAI file upload timed out after 60s")
```

### 3. GitHub Actions Job Timeouts
**Location**: `.github/workflows/content-pipeline-create.yml`

Adds `timeout-minutes` to all jobs:
- `extract-news`: 15 minutes
- `fetch-content`: 20 minutes
- `create-facts-batch`: 30 minutes
- `report-status`: 5 minutes

```yaml
create-facts-batch:
  runs-on: ubuntu-latest
  timeout-minutes: 30  # Prevent zombie workflows - force fail if stuck
```

**Effect**: Workflow is force-failed if any job exceeds timeout, preventing 6-hour zombie runs.

---

## Batch Status Tracking

### New "CREATING" Status

Added `BatchStatus.CREATING` to track in-progress batch creation:

**Status Flow**:
```
┌─────────────┐     Creation     ┌──────────┐     OpenAI      ┌─────────┐
│ No Batch    │─────Started─────▶│ CREATING │────Submitted───▶│ PENDING │
└─────────────┘                  └──────────┘                 └─────────┘
       │                              │
       │                              │ Timeout/Error
       │                              ▼
       │                         ┌────────┐
       └────────────────────────▶│ FAILED │
                                 └────────┘
```

### New Tracking Methods

**`mark_creation_started(stage, article_count, model)`**
- Creates a temporary batch record with `status='creating'`
- Prevents concurrent creation attempts
- Called **before** starting batch creation

**`mark_creation_completed(creating_batch_id, actual_batch_id)`**
- Updates CREATING batch to PENDING with actual OpenAI batch ID
- Called **after** successful batch submission

**`get_stale_creating_batches(max_age_minutes=30)`**
- Finds batches stuck in CREATING for >30 minutes
- Used by cleanup workflows to detect hung creation processes

### Updated `has_active_batches()`

Now includes `CREATING` status in active batch check:
```python
active_statuses = [
    BatchStatus.CREATING,   # NEW - prevents concurrent creation
    BatchStatus.PENDING,
    BatchStatus.COMPLETED,
    BatchStatus.PROCESSING,
]
```

---

## Usage

### Automatic Protection (Recommended)

All timeout protections are **automatic** and enabled by default:
1. Content fetching times out after 10 minutes
2. OpenAI API calls time out after 60s/30s
3. GitHub Actions jobs time out after configured minutes
4. `has_active_batches()` prevents concurrent creation

No configuration needed - timeouts are hardcoded at safe values.

### Manual Cleanup (When Needed)

If batch creation gets stuck despite timeouts:

```bash
# Check for stale CREATING batches
python scripts/cleanup_stale_batches.py --dry-run

# Mark stale batches as failed (default: >30 min old)
python scripts/cleanup_stale_batches.py

# Custom timeout and stage filter
python scripts/cleanup_stale_batches.py --max-age 20 --stage facts
```

**When to use**:
- Workflow stuck for >30 minutes
- `has_active_batches()` reports true but no batch visible
- Manual intervention needed to unblock pipeline

---

## Configuration

### Timeout Values

| Component | Timeout | Configurable | Location |
|-----------|---------|--------------|----------|
| **Content Fetching** | 10 min | Hardcoded | `request_generator.py:CONTENT_FETCH_TIMEOUT` |
| **OpenAI File Upload** | 60s | Hardcoded | `pipeline.py:OPENAI_FILE_UPLOAD_TIMEOUT` |
| **OpenAI Batch Create** | 30s | Hardcoded | `pipeline.py:OPENAI_BATCH_CREATE_TIMEOUT` |
| **GitHub Actions Jobs** | 15-30 min | Per job | `.github/workflows/*.yml` |
| **Stale Creation** | 30 min | CLI arg | `--max-age` in cleanup script |

### Recommended Values

Based on observed production performance:

| Stage | Typical Time | Timeout | Safety Margin |
|-------|--------------|---------|---------------|
| **Facts Content** | 5-10 min | 10 min | 2x |
| **Facts Creation** | 2-5 min | 30 min (job) | 6-15x |
| **OpenAI Upload** | 5-15s | 60s | 4-12x |
| **OpenAI Batch** | 1-3s | 30s | 10-30x |

**Tuning**: If legitimate operations hit timeouts, increase timeout constants in code.

### Environment Variables

No environment variables needed - all timeouts are hardcoded for simplicity and reliability.

To customize, edit the constants directly:
```python
# In request_generator.py
CONTENT_FETCH_TIMEOUT = 600  # Change to 900 for 15 minutes

# In pipeline.py
OPENAI_FILE_UPLOAD_TIMEOUT = 60  # Change to 120 for 2 minutes
OPENAI_BATCH_CREATE_TIMEOUT = 30  # Change to 60 for 1 minute
```

---

## Monitoring

### Logs to Watch

**Content Fetching Timeout**:
```
Content fetch progress: 50/100 (45 successful)
WARNING: Content fetching timed out after 600s
```

**OpenAI API Timeout**:
```
Uploading batch file to OpenAI...
ERROR: TimeoutError: OpenAI file upload timed out after 60s
```

**GitHub Actions Timeout**:
```
Error: The operation was canceled.
```

**Stale Creation Detection**:
```
WARNING: Found 1 batches stuck in CREATING status for >30 minutes
```

### Metrics to Track

1. **Batch creation duration** - how long from start to PENDING
2. **Content fetching duration** - time in parallel fetching
3. **OpenAI API latency** - file upload + batch create time
4. **Stale CREATING count** - batches stuck >30 min

---

## Database Migration

Apply the migration to add `CREATING` status:

```sql
-- Run in Supabase SQL Editor
-- File: supabase/migrations/20251205000000_add_creating_status.sql

ALTER TABLE batch_jobs DROP CONSTRAINT IF EXISTS batch_jobs_status_check;
ALTER TABLE batch_jobs ADD CONSTRAINT batch_jobs_status_check
CHECK (status IN ('creating', 'pending', 'completed', 'processing', 'processed', 'failed', 'cancelled'));
```

**OR** if using enum type:
```sql
ALTER TYPE batch_status ADD VALUE IF NOT EXISTS 'creating';
```

---

## Rollback Plan

If timeouts cause issues, rollback steps:

### 1. Revert Code Changes
```bash
git revert <commit-hash>  # Revert timeout protection commits
```

### 2. Revert Database
```sql
-- Remove 'creating' from status constraint
ALTER TABLE batch_jobs DROP CONSTRAINT IF EXISTS batch_jobs_status_check;
ALTER TABLE batch_jobs ADD CONSTRAINT batch_jobs_status_check
CHECK (status IN ('pending', 'completed', 'processing', 'processed', 'failed', 'cancelled'));

-- Mark any CREATING batches as FAILED
UPDATE batch_jobs SET status = 'failed', error_message = 'Rollback: creating status removed'
WHERE status = 'creating';
```

### 3. Disable Job Timeouts
Remove `timeout-minutes` from `.github/workflows/content-pipeline-create.yml`.

---

## Testing

### Test Content Fetching Timeout

Simulate slow URL fetching:
```python
# In request_generator.py, temporarily add:
import time
time.sleep(700)  # Trigger 10-minute timeout
```

Expected: Timeout after 600s, processes partial results.

### Test OpenAI API Timeout

Simulate slow API:
```python
# In pipeline.py, temporarily reduce timeout:
OPENAI_FILE_UPLOAD_TIMEOUT = 1  # Force immediate timeout
```

Expected: `TimeoutError` raised, batch creation fails gracefully.

### Test GitHub Actions Timeout

Set very short timeout:
```yaml
timeout-minutes: 1  # Force timeout
```

Expected: Job fails with "operation was canceled" after 1 minute.

### Test Stale Creation Cleanup

```bash
# Create a fake CREATING batch directly in DB
INSERT INTO batch_jobs (batch_id, stage, status, created_at)
VALUES ('test_creating', 'facts', 'creating', NOW() - INTERVAL '1 hour');

# Run cleanup
python scripts/cleanup_stale_batches.py --dry-run

# Should report 1 stale batch
```

---

## Future Improvements

1. **Stage-specific timeouts**: Different timeouts for facts/knowledge/summary
2. **Dynamic timeout adjustment**: Learn from historical performance
3. **Retry with exponential backoff**: Auto-retry on timeout with longer timeout
4. **Alerting**: Send notifications when timeouts occur repeatedly
5. **Metrics dashboard**: Track timeout frequency and duration trends

---

## See Also

- **Batch Tracking**: `src/shared/batch/tracking.py` - Core tracking implementation
- **Facts Pipeline**: `src/functions/url_content_extraction/core/facts_batch/` - Where timeouts are applied
- **GitHub Workflows**: `.github/workflows/content-pipeline-*.yml` - Pipeline orchestration
- **Architecture**: `docs/architecture/function_isolation.md` - Overall system design
