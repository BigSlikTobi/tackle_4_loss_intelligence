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

```bash
# Check what needs processing
python scripts/extract_knowledge_cli.py --progress

# Test first (no database writes)
python scripts/extract_knowledge_cli.py --dry-run --limit 5

# Process all unextracted groups
python scripts/extract_knowledge_cli.py

# Process specific number with verbose logging
python scripts/extract_knowledge_cli.py --limit 100 --verbose
```

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
- ✅ Batch processing with pagination (1000 rows per page)
- ✅ Connection pooling and reuse
- ✅ Memory-efficient streaming
- ✅ Progress tracking and checkpointing

**Cost Optimization:**
- ✅ GPT-5-mini with medium reasoning (~$3-10 per 1,000 groups)
- ✅ Batch operations to minimize API calls
- ✅ Smart caching of entity lookups

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
| extracted_at    | TIMESTAMPTZ | Extraction timestamp                        |

**Indexes:**
- `idx_story_entities_group_id` - Lookup entities for a group
- `idx_story_entities_type_id` - Reverse lookup (e.g., all stories about Mahomes)
- `idx_story_entities_primary` - Filter primary entities

**Example Entities:**
- `{type: 'player', entity_id: '00-0033873', mention_text: 'Patrick Mahomes'}`
- `{type: 'team', entity_id: 'KC', mention_text: 'Chiefs'}`
- `{type: 'game', entity_id: '2024_01_KC_LAC', mention_text: 'Chiefs vs Chargers'}`

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

## Pipeline Stages

### 1. Story Reading
**Module:** `core/db/story_reader.py`
- Queries story_groups LEFT JOIN story_topics (finds unextracted)
- Paginates results (1000 rows per batch)
- Fetches group summaries for extraction

### 2. Topic Extraction
**Module:** `core/extraction/topic_extractor.py`
- Uses GPT-5-mini with medium reasoning
- Extracts 2-4 word topic phrases
- Normalizes to lowercase for consistency
- Returns confidence scores

### 3. Entity Extraction
**Module:** `core/extraction/entity_extractor.py`
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
