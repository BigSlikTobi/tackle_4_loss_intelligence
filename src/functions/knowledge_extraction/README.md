# Knowledge Extraction Module

**Extracts key topics and NFL entities from story groups** using GPT-5-mini reasoning model to build a knowledge graph for cross-referencing and analysis.

---

## Overview

**What it does:** Uses LLM-based extraction with fuzzy entity matching to identify key topics (e.g., "QB performance", "injury update") and resolve entities (players, teams, games) to database IDs, enabling sophisticated cross-referencing across unrelated story groups.

**Status:** ✅ Production Ready

**Key Features:**
- 🧠 **GPT-5-mini with medium reasoning** - Optimized cost/performance balance ($3-10 per 1K groups)
- 🔄 **Production resilience** - Retry logic, circuit breakers, rate limiting, timeout handling
- 🎯 **Fuzzy entity matching** - Handles nicknames, abbreviations, and variations
- 🔒 **Player disambiguation** - Requires 2+ identifying hints (name + position/team) to prevent ambiguity
- 🏆 **Importance ranking** - Entities and topics ranked by relevance (rank 1=main, 2=secondary, 3+=minor)
- 📊 **Batch processing** - Efficient pagination and progress tracking
- 🧪 **Dry-run mode** - Test extraction without database writes
- 📈 **Comprehensive monitoring** - Error tracking and performance metrics

---

## Quick Start

### 1. Install

```bash
cd src/functions/knowledge_extraction
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure

Add to **central `.env`** file at project root:

```bash
# Required
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-service-role-key
OPENAI_API_KEY=sk-your-openai-api-key

# Optional: Extraction tuning
MAX_TOPICS_PER_GROUP=10          # Max topics per group (default: 10)
MAX_ENTITIES_PER_GROUP=20        # Max entities per group (default: 20)
ENTITY_CONFIDENCE_THRESHOLD=0.7  # Min confidence for matches (default: 0.7)
```

### 3. Create Database Tables

Run `schema.sql` in **Supabase SQL Editor**:

1. Go to https://your-project.supabase.co
2. Navigate to **SQL Editor** → **New query**
3. Copy entire contents of `schema.sql`
4. Click **Run**

This creates:
- `story_topics` - Key topics for cross-referencing
- `story_entities` - Linked entities (players, teams, games)
- Views and indexes for efficient queries
- Helper functions for lookups

### 4. Extract Knowledge

#### Option A: Batch Processing (Recommended for Large Volumes)

**💰 50% cost savings | ⏱ 24-hour completion | 📦 Process up to 50,000 groups**

```bash
# Check what needs processing
python scripts/extract_knowledge_cli.py --progress

# Create batch job for all unextracted groups
python scripts/extract_knowledge_cli.py --batch

# Create batch job with automatic completion monitoring
python scripts/extract_knowledge_cli.py --batch --wait

# Create batch for specific number of groups
python scripts/extract_knowledge_cli.py --batch --limit 1000

# Check status of a batch job
python scripts/extract_knowledge_cli.py --batch-status batch_abc123

# Process completed batch results
python scripts/extract_knowledge_cli.py --batch-process batch_abc123

# List recent batch jobs
python scripts/extract_knowledge_cli.py --batch-list

# Cancel a running batch
python scripts/extract_knowledge_cli.py --batch-cancel batch_abc123
```

**When to use batch processing:**
- ✅ Processing 100+ story groups (significant cost savings)
- ✅ Non-urgent workloads (24h completion time acceptable)
- ✅ Large-scale backfills or historical data processing
- ✅ Budget-constrained projects (50% cheaper than synchronous)

**Cost Example (3,500 groups):**
- Synchronous: ~$35-70 (2 API calls per group × $0.01-0.02 per call)
- **Batch: ~$17-35** (50% discount) 💰

#### Option B: Synchronous Processing (Real-time)

**⚡ Immediate results | 🔄 Real-time progress | 📊 Detailed logging**

```bash
# Test first (no database writes)
python scripts/extract_knowledge_cli.py --dry-run --limit 5

# Process all unextracted groups
python scripts/extract_knowledge_cli.py

# Process specific number with verbose logging
python scripts/extract_knowledge_cli.py --limit 100 --verbose

# Retry failed extractions
python scripts/extract_knowledge_cli.py --retry-failed
```

**When to use synchronous processing:**
- ✅ Small volumes (<100 groups) where cost difference is minimal
- ✅ Urgent/time-sensitive extraction needs
- ✅ Development and testing (immediate feedback)
- ✅ When you need detailed real-time progress logging

---

## Architecture

### Pipeline Flow

```
┌─────────────────────┐
│ Story Groups        │
│ (from grouping)     │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ Story Reader        │  ← Load unextracted groups (pagination)
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ Entity Extractor    │  ← GPT-5-mini extracts players/teams/games
│ + Topic Extractor   │  ← GPT-5-mini extracts key topics
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ Entity Resolver     │  ← Fuzzy match to database IDs
│ (Fuzzy Matching)    │     player_id, team_abbr, game_id
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ Knowledge Writer    │  ← Upsert to database
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ story_topics        │  ← Cross-reference topics
│ story_entities      │  ← Linked entities
└─────────────────────┘
```

### Production Features

**Resilience:**
- ✅ Exponential backoff retry on rate limits
- ✅ Circuit breaker after consecutive failures (auto-reset after 5min)
- ✅ Timeout handling (60s default)
- ✅ Comprehensive error logging

**Scalability:**
- ✅ **Batch processing via OpenAI Batch API** (up to 50,000 groups per batch)
- ✅ Database pagination (1000 rows per page)
- ✅ Connection pooling and reuse
- ✅ Memory-efficient streaming
- ✅ Progress tracking and checkpointing

**Cost Optimization:**
- ✅ **50% cost savings with batch processing** (OpenAI Batch API discount)
- ✅ GPT-5-mini with medium reasoning (~$3-10 per 1,000 groups synchronous, $1.50-5 batch)
- ✅ Batch operations to minimize API overhead
- ✅ Smart caching of entity lookups

### Batch Processing Architecture

**Batch processing workflow:**

```
┌─────────────────────┐
│ 1. Generate Requests│  ← Create .jsonl file with all extraction requests
│    (request_generator)│     Format: {custom_id, method, url, body}
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ 2. Upload to OpenAI │  ← Upload .jsonl via Files API
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ 3. Create Batch Job │  ← Create batch via Batches API
│    (batch_abc123)   │     Status: validating → in_progress → completed
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ 4. Poll Status      │  ← Check status periodically (60s intervals)
│    (optional wait)  │     Track: total, completed, failed counts
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ 5. Download Results │  ← Fetch output file when completed
│    (output.jsonl)   │     Contains responses for all requests
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ 6. Process Results  │  ← Parse responses, resolve entities
│    (result_processor)│     Write to database
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ story_topics        │  ← Knowledge extracted and saved
│ story_entities      │
└─────────────────────┘
```

**Batch Processing Benefits:**
- 💰 **50% cost reduction** vs synchronous API calls
- 📦 **Higher throughput**: Process up to 50,000 groups per batch
- ⏱ **Predictable completion**: 24-hour guarantee
- 🔄 **Automatic retries**: Built-in by OpenAI
- 📊 **Progress tracking**: Monitor status via CLI

---

## Advanced Features

### 🔒 Player Disambiguation

**Requires 2+ identifying hints per player to prevent ambiguity.**

**Problem:** Players with common names (e.g., "Josh Allen") cannot be uniquely identified without context.

**Solution:** The system uses a two-layer approach:
1. **Extraction Layer**: Requires name + (position OR team) for every player
2. **Resolution Layer**: Uses disambiguation info to filter database matches

**How It Works:**

When the LLM extracts "Allen" with position="QB" and team="Bills":
1. Extraction validates: Has position OR team? ✅ Pass
2. Resolution finds all "Allen" players in database
3. Resolution filters: Keep only players where position=QB AND team=BUF
4. Result: Only Josh Allen (Bills QB) matches, not Josh Allen (Jaguars LB)

**Examples:**

| Extraction | Resolution Behavior | Result |
|------------|---------------------|--------|
| "Josh Allen" + position="QB" | Filters to only QB players named Josh Allen | ✅ Josh Allen (Bills QB) |
| "Allen" + position="QB" + team="Bills" | Filters to only Bills QBs named Allen | ✅ Josh Allen (Bills QB) |
| "Allen" + position="LB" | Filters to only LB players named Allen | ✅ Josh Allen (Jaguars LB) |
| "Mahomes" + team="Chiefs" | Filters to only Chiefs players named Mahomes | ✅ Patrick Mahomes |
| "Josh Allen" (no context) | ❌ Rejected at extraction (missing disambiguation) | ❌ Not extracted |

**Database Fields:**
```python
position: str      # QB, RB, WR, TE, etc.
team_abbr: str     # BUF, KC, SF, etc.
team_name: str     # Bills, Chiefs, 49ers, etc.
```

**Benefits:**
- Distinguishes Josh Allen QB (Bills) from Josh Allen LB (Jaguars)
- Higher extraction accuracy
- Better downstream entity resolution
- Clear validation logs

### 🏆 Importance Ranking

**Entities and topics are ranked by relevance for better organization.**

**Ranking System:**
- **Rank 1**: Main subject(s) - primary focus of the story
- **Rank 2**: Secondary - important supporting entities/topics
- **Rank 3+**: Tertiary - minor mentions

**Example Story:**
```
"Josh Allen threw for 3 touchdowns as the Bills defeated the Dolphins 35-23. 
Stefon Diggs caught 2 TDs. James Cook added a rushing touchdown."
```

**Extracted with Rankings:**

| Entity/Topic | Type | Rank | Reason |
|--------------|------|------|--------|
| Josh Allen | player | 1 | Main subject, primary action |
| Buffalo Bills | team | 1 | Winning team |
| qb performance | topic | 1 | Primary theme |
| Stefon Diggs | player | 2 | Secondary subject |
| Miami Dolphins | team | 2 | Opponent |
| James Cook | player | 3 | Minor mention |

**Query Examples:**
```sql
-- Get only main subjects
SELECT * FROM story_entities 
WHERE story_group_id = 'abc-123' AND rank = 1
ORDER BY confidence DESC;

-- Get top 3 most important entities
SELECT * FROM story_entities 
WHERE story_group_id = 'abc-123'
ORDER BY rank ASC, confidence DESC
LIMIT 3;

-- Get primary and secondary only
SELECT * FROM story_entities 
WHERE story_group_id = 'abc-123' AND rank <= 2
ORDER BY rank, confidence DESC;
```

**Frontend Benefits:**
- Display "Main Players" vs "Also Mentioned"
- Show top N entities efficiently
- Better UX with organized information
- Focus analytics on primary entities

---

## Database Schema

### `story_topics`

Stores key topics extracted from story groups as searchable text.

| Column          | Type        | Description                                 |
|-----------------|-------------|---------------------------------------------|
| id              | UUID        | Primary key                                 |
| story_group_id  | UUID        | Foreign key to story_groups                 |
| topic           | TEXT        | Normalized topic (lowercase)                |
| confidence      | REAL        | LLM confidence score (0.0-1.0)              |
| rank            | INTEGER     | Importance ranking (1=main, 2=secondary, 3+=minor) |
| extracted_at    | TIMESTAMPTZ | Extraction timestamp                        |

**Indexes:**
- `idx_story_topics_group_id` - Lookup topics for a group
- `idx_story_topics_topic` - Find groups by topic (cross-referencing)
- `idx_story_topics_topic_gin` - Full-text search on topics

**Example Topics:**
- "qb performance", "injury update", "trade rumors", "playoff implications"

### `story_entities`

Links story groups to specific NFL entities (polymorphic design).

| Column          | Type        | Description                                 |
|-----------------|-------------|---------------------------------------------|
| id              | UUID        | Primary key                                 |
| story_group_id  | UUID        | Foreign key to story_groups                 |
| entity_type     | TEXT        | 'player', 'team', or 'game'                 |
| entity_id       | TEXT        | player_id, team_abbr, or game_id            |
| mention_text    | TEXT        | Original text from story                    |
| confidence      | REAL        | Resolution confidence (0.0-1.0)             |
| is_primary      | BOOLEAN     | Main subject vs. mention                    |
| position        | TEXT        | Player position (QB, RB, etc.) - for disambiguation |
| team_abbr       | TEXT        | Player team abbreviation - for disambiguation |
| team_name       | TEXT        | Player team name - for disambiguation       |
| rank            | INTEGER     | Importance ranking (1=main, 2=secondary, 3+=minor) |
| extracted_at    | TIMESTAMPTZ | Extraction timestamp                        |

**Indexes:**
- `idx_story_entities_group_id` - Lookup entities for a group
- `idx_story_entities_type_id` - Reverse lookup (e.g., all stories about Mahomes)
- `idx_story_entities_primary` - Filter primary entities

**Example Entities:**
- `{type: 'player', entity_id: '00-0033873', mention_text: 'Patrick Mahomes', position: 'QB', team_name: 'Chiefs'}`
- `{type: 'team', entity_id: 'KC', mention_text: 'Chiefs'}`
- `{type: 'game', entity_id: '2024_01_KC_LAC', mention_text: 'Chiefs vs Chargers'}`

**Player Disambiguation Fields:**
For player entities, at least one of `position`, `team_abbr`, or `team_name` must be present.
This ensures accurate identification of players with common names (e.g., Josh Allen QB vs Josh Allen LB).

### Utility Views

**`story_player_entities`** - Joins entities with player details:
```sql
SELECT * FROM story_player_entities 
WHERE player_id = '00-0033873' 
ORDER BY extracted_at DESC;
```

**`story_team_entities`** - Joins entities with team details:
```sql
SELECT * FROM story_team_entities 
WHERE team_abbr = 'KC' 
ORDER BY extracted_at DESC;
```

**`story_game_entities`** - Joins entities with game details:
```sql
SELECT * FROM story_game_entities 
WHERE game_id = '2024_01_KC_LAC';
```

---

## Usage Examples

### CLI Options

```bash
# Progress tracking
--progress              Show extraction progress and statistics
--limit N               Process only N groups (default: all)
--dry-run              Test extraction without writing to database
--verbose              Enable debug logging

# Examples
python scripts/extract_knowledge_cli.py --progress
python scripts/extract_knowledge_cli.py --dry-run --limit 10 --verbose
python scripts/extract_knowledge_cli.py --limit 1000
```

### Query Examples

**Find all stories about Patrick Mahomes:**
```sql
SELECT sg.*, se.mention_text, se.confidence
FROM story_entities se
JOIN story_groups sg ON sg.id = se.story_group_id
WHERE se.entity_type = 'player' 
  AND se.entity_id = '00-0033873'
ORDER BY se.extracted_at DESC;
```

**Find stories with "qb performance" topic:**
```sql
SELECT sg.*, st.topic, st.confidence
FROM story_topics st
JOIN story_groups sg ON sg.id = st.story_group_id
WHERE st.topic ILIKE '%qb performance%'
ORDER BY st.confidence DESC;
```

**Cross-reference unrelated story groups by topic:**
```sql
SELECT DISTINCT sg1.id AS group1, sg2.id AS group2, st1.topic
FROM story_topics st1
JOIN story_topics st2 ON st1.topic = st2.topic AND st1.story_group_id != st2.story_group_id
JOIN story_groups sg1 ON sg1.id = st1.story_group_id
JOIN story_groups sg2 ON sg2.id = st2.story_group_id
WHERE st1.confidence >= 0.8
  AND st2.confidence >= 0.8
LIMIT 100;
```

**Find all Chiefs-related stories:**
```sql
SELECT * FROM find_groups_by_entity('team', 'KC')
ORDER BY is_primary DESC, confidence DESC;
```

---

## Batch Processing Workflow

### Complete Example: Processing 3,500 Story Groups

**Step 1: Check Progress**
```bash
python scripts/extract_knowledge_cli.py --progress
```

Output:
```
============================================================
KNOWLEDGE EXTRACTION PROGRESS
============================================================
Total story groups:        3,500
Groups with extraction:    0
Groups remaining:          3,500
Failed groups:             0
...
💡 Use --batch flag for 50% cost savings on large volumes!
```

**Step 2: Create Batch Job**
```bash
python scripts/extract_knowledge_cli.py --batch
```

Output:
```
================================================================================
Generating Batch Request File
================================================================================
Loading groups (limit: all, retry_failed: False)...
Generating requests for 3500 story groups...
Writing 7000 requests to ./batch_files/knowledge_extraction_batch_20251005_143022.jsonl

Batch file generated: ./batch_files/knowledge_extraction_batch_20251005_143022.jsonl
Total groups: 3500
Total requests: 7000 (2 per group: topics + entities)

Step 2: Uploading file to OpenAI: ./batch_files/...
File uploaded with ID: file-abc123

Step 3: Creating batch job...
Batch created with ID: batch_xyz789
Status: validating

================================================================================
Batch Job Created Successfully
================================================================================
Batch ID: batch_xyz789
Status: validating
Total groups: 3500
Total requests: 7000

To check status later, run:
  python extract_knowledge_cli.py --batch-status batch_xyz789
```

**Step 3: Monitor Progress** (periodic checks)
```bash
python scripts/extract_knowledge_cli.py --batch-status batch_xyz789
```

Output:
```
============================================================
BATCH STATUS
============================================================
Batch ID:       batch_xyz789
Status:         in_progress

Progress:
  Total:        7000
  Completed:    3200
  Failed:       5
  Complete:     45.7%

Created at:     2025-10-05 14:30:22

⏳ Batch is in_progress. Check again later with:
   python extract_knowledge_cli.py --batch-status batch_xyz789
```

**Step 4: Process Results** (when completed)
```bash
python scripts/extract_knowledge_cli.py --batch-process batch_xyz789
```

Output:
```
================================================================================
Processing Batch Results: batch_xyz789
================================================================================
Downloading output file: file-output123
Output saved to: ./batch_files/batch_xyz789_output_20251006_102030.jsonl

Processing results and writing to database...

[1/3500] Processing group abc-123-def
Resolved 12 entities
Wrote 5 topics and 12 entities

[2/3500] Processing group abc-124-def
...

============================================================
BATCH PROCESSING RESULTS
============================================================
Batch ID:           batch_xyz789
Groups processed:   3495
Topics extracted:   17,450
Entities extracted: 41,200
Groups with errors: 5
============================================================

✅ Results saved to database!
```

**Step 5: Verify Results**
```bash
python scripts/extract_knowledge_cli.py --progress
```

Output:
```
============================================================
KNOWLEDGE EXTRACTION PROGRESS
============================================================
Total story groups:        3,500
Groups with extraction:    3,495
Groups remaining:          5
Failed groups:             5

Total topics extracted:    17,450
Total entities extracted:  41,200

Avg topics per group:      5.0
Avg entities per group:    11.8
============================================================

⚠️  5 groups failed - use --retry-failed to retry
```

### Batch Processing Tips

**For Large Volumes (1000+):**
```bash
# Create batch and wait for completion (auto-process when done)
python scripts/extract_knowledge_cli.py --batch --wait

# Or break into smaller batches
python scripts/extract_knowledge_cli.py --batch --limit 1000
# Wait for completion, then process next batch
```

**Monitoring Active Batches:**
```bash
# List all recent batches
python scripts/extract_knowledge_cli.py --batch-list

# Check specific batch
python scripts/extract_knowledge_cli.py --batch-status batch_xyz789
```

**Handling Failures:**
```bash
# Retry failed groups (after processing main batch)
python scripts/extract_knowledge_cli.py --retry-failed --limit 10

# Or create new batch for failed groups
python scripts/extract_knowledge_cli.py --batch --retry-failed
```

**Cost Comparison:**
- **Synchronous (3,500 groups)**: ~$35-70 (7,000 API calls @ $0.005-0.01 each)
- **Batch (3,500 groups)**: ~$17-35 (50% discount) 💰
- **Savings**: $18-35 per run

**Time Comparison:**
- **Synchronous**: 2-4 hours (with rate limits)
- **Batch**: 12-24 hours (but hands-off, no monitoring needed)

---

## Pipeline Stages

### 1. Story Reading
**Module:** `core/db/story_reader.py`
- Queries story_groups LEFT JOIN story_topics (finds unextracted)
- Paginates results (1000 rows per batch)
- Fetches group summaries for extraction

### 2. Topic Extraction
**Module:** `core/extraction/topic_extractor.py` (synchronous) or `core/batch/request_generator.py` (batch)
- Uses GPT-5-mini with medium reasoning
- Extracts 2-4 word topic phrases
- Normalizes to lowercase for consistency
- Returns confidence scores

### 3. Entity Extraction
**Module:** `core/extraction/entity_extractor.py` (synchronous) or `core/batch/request_generator.py` (batch)
- Uses GPT-5-mini with medium reasoning
- Identifies players, teams, games
- Captures mention text and context
- Marks primary vs. secondary mentions

### 4. Entity Resolution
**Module:** `core/resolution/entity_resolver.py`
- Fuzzy matches entities to database
- Handles nicknames and abbreviations
- Uses rapidfuzz for performance
- Applies confidence thresholds

**Matching Examples:**
- "Mahomes" → player_id: `00-0033873` (Patrick Mahomes)
- "Chiefs" → team_abbr: `KC`
- "KC vs LAC Week 1" → game_id: `2024_01_KC_LAC`

### 5. Knowledge Writing
**Module:** `core/db/knowledge_writer.py`
- Upserts topics (deduplicates by group + topic)
- Upserts entities (deduplicates by group + type + id)
- Supports dry-run mode
- Returns write statistics

---

## Status Tracking & Retry System

The extraction system uses a dedicated status table to track progress, handle retries, and detect failures.

### Status Values

| Status | Description |
|--------|-------------|
| `pending` | Not yet processed (or reset for reprocessing) |
| `processing` | Currently being extracted |
| `completed` | Successfully extracted topics and entities |
| `failed` | Extraction failed (with error message stored) |
| `partial` | Some data extracted but not complete |

### Key Features

**Automatic Status Tracking:**
- Status updates automatically during extraction
- Tracks timestamps: `started_at`, `completed_at`, `last_attempt_at`
- Records counts: `topics_extracted`, `entities_extracted`

**Error Tracking:**
- Stores error messages (truncated to 1000 chars)
- Increments `error_count` on each failure
- Prevents infinite retry loops with `max_errors` threshold

**Retry Failed Extractions:**
```bash
# Retry failed extractions (max 3 errors per group)
python scripts/extract_knowledge_cli.py --retry-failed

# Retry with custom error threshold
python scripts/extract_knowledge_cli.py --retry-failed --max-errors 5

# Check progress with status breakdown
python scripts/extract_knowledge_cli.py --progress
```

### Monitoring Queries

**Check failed groups:**
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

**Get success rate:**
```sql
SELECT 
    status,
    COUNT(*) as count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) as percentage
FROM story_group_extraction_status
GROUP BY status;
```

**Check groups stuck in processing (>30 mins):**
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

---

## Error Handling

### Retry Logic

**Rate Limits:** Exponential backoff (2s, 4s, 8s, 16s, max 60s)
```
Attempt 1: Immediate
Attempt 2: Wait 2s
Attempt 3: Wait 4s
```

**Timeouts:** Default 60s per API call, retry with backoff

**Circuit Breaker:** Opens after 5 consecutive failures, auto-resets after 5 minutes

### Common Issues

**Issue:** `Circuit breaker is open`
**Solution:** Wait 5 minutes for auto-reset, or investigate underlying failures

**Issue:** `Rate limit exceeded`
**Solution:** Reduce batch size, add delays, or upgrade OpenAI tier

**Issue:** `No unextracted groups found`
**Solution:** Check that story groups exist and haven't all been processed

---

## Cost Estimation

**GPT-5-mini Pricing (as of Oct 2025):**
- Input: ~$0.10 per 1M tokens
- Output: ~$0.40 per 1M tokens

**Typical Usage:**
- Average summary: ~300 tokens input, ~150 tokens output per group
- 2 API calls per group (topics + entities)
- **Cost:** ~$3-10 per 1,000 story groups

**Production Recommendations:**
- Process in batches of 100-500 groups
- Monitor API usage in OpenAI dashboard
- Use --limit flag for cost control during testing

---

## Monitoring

### Progress Tracking

```bash
python scripts/extract_knowledge_cli.py --progress
```

Output:
```
============================================================
EXTRACTION PROGRESS
============================================================
Total story groups:           1,234
Groups with topics/entities:  456
Groups remaining:             778
Completion:                   37.0%
============================================================
```

### Metrics

The extraction pipeline tracks:
- ✅ Groups processed
- ✅ Topics extracted
- ✅ Entities extracted
- ✅ Entities resolved (with confidence)
- ✅ Errors encountered
- ✅ Processing time

---

## Module Structure

```
knowledge_extraction/
├── core/
│   ├── db/
│   │   ├── story_reader.py       # Read unextracted groups
│   │   └── knowledge_writer.py   # Write topics/entities
│   ├── extraction/
│   │   ├── entity_extractor.py   # LLM entity extraction
│   │   └── topic_extractor.py    # LLM topic extraction
│   ├── resolution/
│   │   └── entity_resolver.py    # Fuzzy entity matching
│   └── pipelines/
│       └── extraction_pipeline.py # Orchestration
├── scripts/
│   └── extract_knowledge_cli.py  # Command-line interface
├── functions/                     # Cloud Function (future)
├── schema.sql                     # Database schema
├── requirements.txt               # Dependencies
└── README.md                      # This file
```

---

## Prerequisites

Before running knowledge extraction:

1. ✅ **Data Loading**: Players, teams, and games loaded
2. ✅ **News Extraction**: News URLs collected
3. ✅ **Content Summarization**: Articles summarized
4. ✅ **Story Embeddings**: Embeddings generated
5. ✅ **Story Grouping**: Stories clustered into groups

---

## Troubleshooting

**Problem:** `relation "public.story_topics" does not exist`
**Solution:** Run `schema.sql` in Supabase SQL Editor

**Problem:** `column teams.full_name does not exist`
**Solution:** Schema already fixed - uses `team_name` instead

**Problem:** `column games.game_date does not exist`
**Solution:** Schema already fixed - uses `gameday` instead

**Problem:** `OpenAI API key required`
**Solution:** Add `OPENAI_API_KEY` to central `.env` file

---

## Production Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for Cloud Function deployment guide.

---

## Support

- **Module Documentation**: This README
- **Main Architecture**: [`docs/architecture/function_isolation.md`](../../../docs/architecture/function_isolation.md)
- **AI Agent Guidelines**: [`AGENTS.md`](../../../AGENTS.md)

---

**Built with production resilience, scalability, and cost optimization.** 🚀
