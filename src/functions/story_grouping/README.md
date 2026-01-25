# Story Grouping Module

**Clusters similar NFL news stories at the fact level** using cosine similarity and centroid-based clustering on individual fact embeddings.

---

## Overview

**What it does:** Groups individual facts extracted from news articles based on their embedding similarity. Each fact is treated as an independent unit, allowing multiple facts from the same article to join different thematic groups based on their content.

**Status:** ✅ Production Ready

**Key Features:**
- Cosine similarity-based clustering (default threshold: 0.8)
- **Fact-level grouping**: Individual facts from the same article can join different groups
- Dynamic centroid calculation using fact embedding vectors
- Batch processing with pagination support
- Dry-run mode for testing
- Progress tracking and comprehensive logging

**Prerequisites:**
- ✅ Fact embeddings generated in `facts_embeddings` (see `content_summarization` + `story_embeddings` modules)
- ✅ Supabase database configured
- ✅ Python 3.10+

---

## Quick Start

### 1. Install

```bash
cd src/functions/story_grouping
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure

Add to **central `.env`** file at project root:

```bash
# Required: Supabase credentials
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-service-role-key

# Optional: Grouping parameters
SIMILARITY_THRESHOLD=0.8  # Default: 0.8 (higher = stricter grouping)
LOG_LEVEL=INFO           # Default: INFO
```

### 3. Create Database Tables

Run `schema.sql` in Supabase SQL Editor to create required tables.

### 4. Run Grouping

```bash
# Check progress first
python scripts/group_stories_cli.py --progress

# Test with dry run
python scripts/group_stories_cli.py --dry-run --limit 10

# Process all ungrouped fact embeddings
python scripts/group_stories_cli.py

# With custom threshold
python scripts/group_stories_cli.py --threshold 0.85 --verbose
```

---

## Programmatic Usage

### Single Story Grouping

To group a single story (e.g., triggered by an event):

```python
from src.functions.story_grouping.functions.main import handle_single_story

result = handle_single_story(
    story_id="news-url-uuid-123",
    table_config={
        "embedding_table": "facts_embeddings",
        "group_table": "story_groups", 
        "member_table": "story_group_members",
        "grouping_key_column": "news_url_id"
    }
)
```

### Configuration

#### Table Configuration
The `handle_single_story` function accepts a `table_config` dictionary to support custom schemas:

| Key | Default | Description |
|-----|---------|-------------|
| `embedding_table` | `facts_embeddings` | Table containing source embeddings |
| `group_table` | `story_groups` | Table to store groups |
| `member_table` | `story_group_members` | Table to store memberships |
| `id_column` | `id` | PK of embedding table |
| `vector_column` | `embedding_vector` | Column containing vector data |
| `grouping_key_column` | `news_url_id` | Column used to identify the story (can be URL or UUID) |
| `is_legacy_schema` | `True` | Set to `False` if reading from a flat table without joins |
| `schema_name` | `public` | Postgres schema containing the tables |
| `resolve_uuid` | `False` | If True, looks up UUID from `news_urls` table using the URL |
| `group_schema_name` | `None` | Optional separate schema for `story_groups` table |

---


---

## Local Development

You can run the Cloud Function locally for testing and debugging using the provided helper script.

### Prerequisites
- Create a `.env` file in the project root with your `SUPABASE_URL` and `SUPABASE_KEY`.
- Install dependencies: `pip install -r src/functions/story_grouping/requirements.txt`

### Running Locally
```bash
./src/functions/story_grouping/functions/run_local.sh
```
This starts the function on `localhost:8080`. You can then trigger it with `curl` (see API section below).

## Cloud Function API

The module is deployed as a Google Cloud Function that exposes an HTTP endpoint for on-demand grouping.

### Triggering via HTTP

You can trigger the grouping logic for a single story using `curl`:

```bash
curl -X POST https://REGION-PROJECT_ID.cloudfunctions.net/story-grouping \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com/story-url",
    "table_config": {
      "embedding_table": "news_urls_embeddings",
      "group_table": "story_groups", 
      "member_table": "story_group_members",
      "grouping_key_column": "url",
      "news_table": "news_urls",
      "is_legacy_schema": false,
      "schema_name": "vector_embeddings"
    }
  }'
```

**Parameters:**

- `story_id` **OR** `url`: (Required) The ID (UUID) or URL string of the story to group.
- `table_config`: (Optional) Overrides for table names and schema options. Use if you have custom tables.
- `group_config`: (Optional) Overrides for grouping logic (e.g., `similarity_threshold`).

**UUID Resolution for URLs:**
If you provide a `url` and set `grouping_key_column` to `"url"`, the function will:
1. Fetch the embedding using the URL string.
2. Query the `news_table` (default: `news_urls` in `public` schema) to find the UUID corresponding to that URL.
3. Use that UUID for the `story_group_members` table.

**Idempotency:**
The function checks if the story (UUID) is already in a group. If it is, it returns the existing group with status `"existing"` and does *not* reprocess the story or create duplicates.

---

## How It Works

### Algorithm Overview

1. **Load Embeddings**: Fetch fact embeddings from `facts_embeddings` joined with `news_facts`/`news_urls` (with pagination)
2. **Load Existing Groups**: Fetch current groups and their centroids from `story_groups` (with pagination)
3. **Similarity Check**: For each **individual fact**:
   - Calculate cosine similarity with all existing group centroids
   - If similarity ≥ threshold, assign to most similar group
   - Otherwise, create a new group
4. **Update Centroids**: Recalculate centroid for groups with new members (centroids represent average of all member fact vectors)
5. **Write Results**: Save groups and memberships to database, storing both `news_url_id` (source article) and `news_fact_id` (specific fact)

### Data Flow

```
┌──────────────────────┐         ┌──────────────────┐         ┌──────────────┐
│facts_embeddings      │         │                  │         │story_        │
│                      │────────▶│  StoryGrouper    │────────▶│groups        │
│Each row = 1 FACT     │         │  (core logic)    │         │              │
│+ news_url_id         │         │                  │         │- centroid    │
│+ news_fact_id        │         │  - similarity    │         │- member_count│
│+ embedding_vector    │         │  - clustering    │         └──────────────┘
└──────────────────────┘         │  - centroid calc │                │
                                 │                  │         ┌──────────────┐
┌──────────────┐                 │  Pipeline        │         │story_group_  │
│Existing      │────────────────▶│  Orchestration   │────────▶│members       │
│Groups        │                 └──────────────────┘         │              │
│- centroids   │                                              │+ news_url_id │
└──────────────┘                                              │+ news_fact_id│
                                                              │+ similarity  │
                                                              │  _score      │
                                                              └──────────────┘

Note: Multiple facts from the same news_url can join different groups
```

### Similarity Threshold

The `SIMILARITY_THRESHOLD` parameter (default: 0.8) controls how similar stories must be to join a group:

```
1.00 ────── Identical (same article)
     │
0.90 ────── Very Strict (near duplicates)
     │
0.85 ────── Strict (same story, minor variations)
     │
0.80 ────── Moderate (default) ← RECOMMENDED
     │
0.75 ────── Loose (similar topics)
```

**Guidelines:**
- **Higher threshold (0.85-0.95)**: More groups, smaller groups, stricter matching
- **Lower threshold (0.70-0.80)**: Fewer groups, larger groups, looser matching
- **Default (0.80)**: Balanced approach for related NFL news stories

### Centroid Calculation

Group centroids are the normalized mean of all member embedding vectors:

```python
centroid = mean(embedding_1, embedding_2, ..., embedding_n)
centroid = centroid / ||centroid||  # Normalize
```

This allows new stories to be compared against the "average" representation of each group.

---

## Database Schema

### `story_groups`

Stores group metadata and centroid embeddings.

| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid | Primary key |
| `centroid_embedding` | vector(1536) | Average embedding of all group members |
| `member_count` | int4 | Number of stories in group |
| `status` | text | Group status ("active", "archived") |
| `created_at` | timestamp | When group was created |
| `updated_at` | timestamp | When group was last modified |

**Indexes:**
- Primary key on `id`
- HNSW index on `centroid_embedding` for fast similarity search

### `story_group_members`

Links individual facts to groups with similarity scores.

| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid | Primary key |
| `group_id` | uuid | Foreign key to `story_groups` |
| `news_url_id` | uuid | Foreign key to `news_urls` (source article) |
| `news_fact_id` | uuid | Foreign key to `news_facts` (specific fact) |
| `similarity_score` | float | Cosine similarity with group centroid (0-1) |
| `added_at` | timestamp | When fact was added to group |

**Constraints:**
- UNIQUE(group_id, news_fact_id) - Each fact can only be in a group once
- Index on `news_url_id` for fast lookup

**Note:** Multiple facts from the same `news_url_id` can join different groups based on their content.

### Views

- **`group_summary`**: Group statistics with member counts
- **`ungrouped_stories`**: Facts with embeddings but no group assignment

See `schema.sql` for complete definitions including indexes, triggers, and helper views.

---

## CLI Reference

### Command

```bash
python scripts/group_stories_cli.py [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--dry-run` | Preview changes without writing to database |
| `--limit N` | Process only N stories |
| `--batch-size N` | Override grouping batch size (default: env `GROUPING_BATCH_SIZE` or 200) |
| `--max-run-size N` | Safety cap on embeddings processed when not forced (default: env `GROUPING_MAX_RUN_SIZE` or 10,000) |
| `--force` | Bypass the safety cap to process all requested embeddings |
| `--verbose` | Enable DEBUG logging |
| `--progress` | Show statistics and exit (no processing) |
| `--threshold FLOAT` | Override similarity threshold (0.0-1.0) |
| `--regroup` | Clear existing groups and regroup all stories |

The CLI now guards against accidental full-database runs. If the planned workload
exceeds `--max-run-size`, it will cap the run or abort unless you explicitly pass
`--force`. Use `--limit` to process the backlog in smaller slices.

### Merging near-duplicate groups

If multiple grouping runs produced very similar groups, you can merge them by
centroid similarity:

```bash
# Preview merges (no writes)
python scripts/merge_story_groups_cli.py --dry-run --threshold 0.93 --days 14

# Execute merges (moves memberships, archives merged groups)
python scripts/merge_story_groups_cli.py --threshold 0.93 --days 14 --max-pairs 200
```

Key flags:
- `--threshold`: centroid similarity required to merge (default: 0.92)
- `--group-limit`: cap how many recent groups to analyze (helps keep memory + DB load predictable)
- `--max-pairs`: limit the number of centroid pairs considered (sorted by similarity)
- `--dry-run`: inspect the plan before writing

The merger de-duplicates memberships (by `news_fact_id` or `news_url_id` when no
fact id), moves remaining memberships to the primary group, and archives merged
groups. Use a conservative threshold and inspect results in `--dry-run` first.

### Examples

**Check Progress:**
```bash
python scripts/group_stories_cli.py --progress
```
Output:
```
GROUPING PROGRESS
Total stories:        2,347
Grouped stories:      2,120
Ungrouped stories:    227
Total groups:         542
Avg group size:       3.91
```

**Test Run:**
```bash
python scripts/group_stories_cli.py --dry-run --limit 10 --verbose
```

**Process Ungrouped Stories:**
```bash
python scripts/group_stories_cli.py
```

**Process with Custom Threshold:**
```bash
# Stricter grouping (more, smaller groups)
python scripts/group_stories_cli.py --threshold 0.90

# Looser grouping (fewer, larger groups)
python scripts/group_stories_cli.py --threshold 0.75
```

**Regroup All Stories:**
```bash
# Preview what will happen
python scripts/group_stories_cli.py --regroup --dry-run

# Execute regrouping
python scripts/group_stories_cli.py --regroup
```

---

## Module Architecture

### Directory Structure

```
story_grouping/
├── core/                      # Business logic
│   ├── db/                    # Database access
│   │   ├── embedding_reader.py  # Read embeddings (with pagination)
│   │   └── group_writer.py      # Write groups (with pagination)
│   ├── clustering/            # Clustering algorithms
│   │   ├── similarity.py        # Cosine similarity, centroids
│   │   └── grouper.py           # Main grouping logic
│   └── pipelines/             # Orchestration
│       └── grouping_pipeline.py # End-to-end workflow
├── scripts/                   # CLI tools
│   ├── _bootstrap.py          # Path setup
│   └── group_stories_cli.py   # Main CLI
├── functions/                 # Cloud Function (future)
│   ├── main.py               # Entry point
│   └── deploy.sh             # Deployment script
├── requirements.txt          # Dependencies
├── schema.sql                # Database schema
└── README.md                 # This file
```

### Key Components

**EmbeddingReader** (`core/db/embedding_reader.py`):
- Fetches story embeddings from database with pagination
- Filters ungrouped stories
- Handles vector format parsing (PostgreSQL pgvector → Python list)

**GroupWriter** (`core/db/group_writer.py`):
- Creates and updates story groups with pagination
- Manages group memberships (bulk insert for performance)
- Handles dry-run mode

**Similarity** (`core/clustering/similarity.py`):
- Calculates cosine similarity between vectors
- Computes group centroids (normalized mean)
- Finds most similar group for a story

**StoryGrouper** (`core/clustering/grouper.py`):
- Main clustering engine
- Loads existing groups
- Assigns stories to groups based on similarity
- Updates centroids dynamically

**GroupingPipeline** (`core/pipelines/grouping_pipeline.py`):
- Orchestrates end-to-end workflow
- Validates configuration
- Tracks progress and statistics
- Handles errors and logging

### Import Patterns

```python
# Within module (relative imports)
from ..db.embedding_reader import EmbeddingReader
from ...core.clustering import calculate_cosine_similarity

# Shared utilities (absolute imports)
from src.shared.utils.logging import setup_logging
from src.shared.db import get_supabase_client

# ❌ Never import between function modules
# from src.functions.story_embeddings... (violates isolation)
```

---

## Performance

### Typical Performance

- **1,000 stories**: ~10-15 seconds (including database I/O)
- **Comparing with 500 groups**: ~5-8 seconds
- **Database writes**: Bulk insert ~100 records/sec

### Pagination

All database queries use pagination (1000 rows per page) to handle large datasets:
- Supabase default limit: 1000 rows per request
- Module automatically pages through all results
- Logs total counts for debugging

### Optimization Tips

1. **Use `--limit` for testing**: Process small batches first
2. **Run during off-peak hours**: For large batch operations
3. **Monitor logs**: Use `--verbose` to identify bottlenecks
4. **Database indexes**: Ensure indexes exist (see `schema.sql`)
5. **Consider archiving**: Set old groups to `status='archived'`

### Recent Optimizations

Large batches (8K+ stories) once triggered Supabase timeouts when fetching active groups and ungrouped embeddings. The 2025 performance pass introduced both schema and code changes that are now part of the default module:

- **Database indexes:** `idx_story_groups_status_created_at`, `idx_story_embeddings_created_at`, `idx_story_embeddings_news_url_id`, `idx_story_embeddings_created_at_news_url_id`, and the partial index `idx_story_embeddings_with_vectors` dramatically reduce range-scan costs. Apply the corresponding migration in `supabase/migrations` if your project predates the change.
- **Reader/writer tweaks:** `group_writer.get_active_groups()` now fetches IDs first, caps batch sizes at 500, removes expensive `ORDER BY` clauses, and guards against unbounded paging. `embedding_reader` mirrors the smaller batches and limits grouped-ID lookups to keep latency predictable.
- **Graceful degradation:** Both readers log partial progress and return the data they already fetched if Supabase hits timeout thresholds, letting the CLI continue instead of hard failing.

If you still encounter timeouts after pulling latest migrations, run `EXPLAIN ANALYZE` against the queries shown above to confirm your database is using the new indexes, or temporarily lower `--days`/`--limit` while the backlog drains.

---

## Troubleshooting

### No stories being grouped

**Cause**: No ungrouped embeddings available

**Solution:**
1. Check embeddings exist: `SELECT COUNT(*) FROM story_embeddings WHERE embedding_vector IS NOT NULL`
2. Check grouping status: `python scripts/group_stories_cli.py --progress`
3. Verify threshold not too high: Try `--threshold 0.75`

### Too many small groups (1-2 members each)

**Cause**: Similarity threshold too high

**Solution:**
```bash
# Lower threshold for more grouping
python scripts/group_stories_cli.py --threshold 0.75 --regroup --dry-run
```

### Groups too large/diverse

**Cause**: Similarity threshold too low

**Solution:**
```bash
# Raise threshold for stricter grouping
python scripts/group_stories_cli.py --threshold 0.90 --regroup --dry-run
```

### Performance issues with many groups

**Cause**: Large number of active groups to compare against

**Solutions:**
1. Process in smaller batches: `--limit 500`
2. Archive old groups: `UPDATE story_groups SET status='archived' WHERE created_at < '2024-01-01'`
3. Add database indexes (included in `schema.sql`)

### Vector format errors

**Cause**: PostgreSQL pgvector returns strings, not Python lists

**Solution**: Module automatically handles this with `parse_vector()` function. If errors persist:
1. Check embedding format in database
2. Update to latest module version
3. Enable `--verbose` logging to see parsing details

---

## Development Guide

### Adding Features

**Module-specific code** → Add to `core/`  
**New CLI tool** → Add to `scripts/`  
**Cloud Function** → Implement in `functions/`

### Testing

```bash
# Test without database writes
python scripts/group_stories_cli.py --dry-run --limit 5

# Test with verbose logging
python scripts/group_stories_cli.py --dry-run --verbose

# Test progress tracking
python scripts/group_stories_cli.py --progress
```

### Architecture Principles

This module follows **function-based isolation** (see `/AGENTS.md`):

- ✅ Complete independence (can be deleted without breaking other modules)
- ✅ Isolated dependencies (`requirements.txt`)
- ✅ No cross-module imports (only uses `src/shared/`)
- ✅ Database queries use pagination for large datasets
- ✅ Separate deployment (independent Cloud Function)

---

## Future Enhancements

- [ ] **Cloud Function deployment**: Automated grouping via HTTP API
- [ ] **Scheduled grouping**: Cron/Cloud Scheduler integration
- [ ] **Group merging**: Combine similar groups
- [ ] **Group splitting**: Divide large/diverse groups
- [ ] **Topic labeling**: Generate descriptive group labels
- [ ] **Visualization dashboard**: View groups and similarity graphs
- [ ] **Incremental centroid updates**: Optimize centroid recalculation
- [ ] **Group quality metrics**: Track group coherence over time

---

## Support

**Module Documentation:** This file  
**Architecture:** `/docs/architecture/function_isolation.md`  
**Configuration:** `/docs/configuration.md`  
**Database Schema:** `schema.sql` (with comments)  
**Development Guidelines:** `/AGENTS.md`

**Troubleshooting:** Use `--verbose` flag for detailed logging
