# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Testing
```bash
# Install dev dependencies (lightweight)
pip install -r requirements-dev.txt

# Run all tests from project root
pytest

# Run tests for a specific module
pytest tests/data_loading
pytest tests/story_embeddings --verbose
```

### Per-Module Development (each module is independent)
```bash
cd src/functions/<module_name>
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Edit with credentials
```

### Running Modules Locally
```bash
# CLI tools (all support --dry-run, --limit, --verbose)
python scripts/players_cli.py --dry-run
python scripts/extract_news_cli.py --dry-run --verbose
python scripts/generate_embeddings_cli.py --progress
python scripts/group_stories_cli.py --dry-run --limit 10
python scripts/extract_knowledge_cli.py --progress

# Local Cloud Function server
cd src/functions/<module>/functions && ./run_local.sh

# Deploy to Cloud Functions
cd src/functions/<module>/functions && ./deploy.sh
```

### Debug Logging
```bash
export LOG_LEVEL=DEBUG  # before invoking any script
```

## Architecture

This is an **NFL data intelligence platform** built on **function-based isolation**: each module under `src/functions/` is completely self-contained and can be developed, tested, and deployed independently.

**Modules** (`src/functions/`): core content pipeline uses `news_extraction`, `url_content_extraction`, `knowledge_extraction`, `content_summarization`, `story_embeddings`, `story_grouping`, and `data_loading`. Additional modules: `article_knowledge_extraction`, `article_summarization`, `article_translation`, `article_validation`, `daily_team_update`, `fuzzy_search`, `game_analysis_package`, `gemini_tts`, `gemini_tts_batch`, `image_selection`, `team_article_generation`, `youtube_search`.

### Module Structure

Every module follows the same layout:
```
src/functions/<module>/
├── core/              # All business logic (never imported externally)
│   ├── contracts/    # Data models (dataclasses/Pydantic)
│   ├── db/           # reader.py + writer.py
│   ├── pipelines/    # Orchestration
│   └── ...           # Module-specific subdirs
├── scripts/           # CLI entrypoints (*_cli.py with --dry-run)
├── functions/         # Cloud Function deployment
│   ├── main.py       # HTTP handler
│   ├── deploy.sh     # Deployment (uses mktemp for safety)
│   └── run_local.sh  # Local server
├── requirements.txt   # Module-specific dependencies
├── .env.example       # Config template
└── README.md          # Module docs
```

### Shared Utilities (`src/shared/`)

Only truly generic code lives here:
- `utils/env.py` — `load_env()` for loading the central `.env`
- `utils/logging.py` — `setup_logging()`
- `db/connection.py` — Supabase client
- `batch/` — Checkpoint, retry, progress tracking, memory monitoring, OpenAI Batch API tracking
- `nlp/entity_resolver.py` — `EntityResolver` (fuzzy player/team/game matching; accepts injected Supabase client)
- `nlp/team_aliases.py` — `NFL_TEAM_ALIASES` dict
- `contracts/knowledge.py` — `ResolvedEntity` dataclass

> `knowledge_extraction/core/resolution/entity_resolver.py` is now a re-export shim pointing at `src/shared/nlp/`. Do not add new logic there.

### Import Rules

```python
# Within a module — use relative imports
from ..core.providers import Provider
from ..data.fetch import fetch_data

# Shared utilities — use absolute imports
from src.shared.utils.logging import setup_logging
from src.shared.db import get_supabase_client
from src.shared.utils.env import load_env

# ❌ NEVER import between function modules
```

### Content Pipeline

The automated content pipeline (GitHub Actions, every 30 min) processes articles through these stages:

1. **News Extraction** (`news_extraction`) — RSS/sitemap URL collection
2. **Content Fetching** (`url_content_extraction`) — Playwright HTML fetch
3. **Facts Extraction** (`url_content_extraction`) — OpenAI Batch API (~24h, 50% cheaper)
4. **Knowledge Extraction** (`knowledge_extraction`) — Topics + entities via GPT-5-mini, fuzzy matching
5. **Summary Generation** (`content_summarization`) — Summaries + *summary* embeddings via Google Gemini (distinct from story embeddings in stage 6)
6. **Story Embeddings** (`story_embeddings`) — OpenAI `text-embedding-3-small` vectors over summaries
7. **Story Grouping** (`story_grouping`) — Cosine similarity clustering

Two coordinated workflows handle this: `content-pipeline-create.yml` (creates batches) and `content-pipeline-poll.yml` (polls and promotes). The `batch_jobs` table tracks stage, status, retry count, and OpenAI file IDs to coordinate both workflows and prevent duplicate processing. Promotions between stages are gated by `MIN_PROMOTION_ITEMS=100`. Manual workflow triggers accept knobs like `force_content_fetch`, `skip news extraction`, and `facts limit`.

### Key Implementation Patterns

**Database queries**: Supabase has a 1000-row default limit. Always paginate using `.range(offset, offset + page_size - 1)` and continue until a partial page is returned. Log total counts fetched.

**LLM calls**: Use OpenAI Batch API for cost efficiency. GPT-5-nano uses `reasoning_effort='low'` and `max_completion_tokens` (no `temperature`). Knowledge extraction uses GPT-5-mini with medium reasoning.

**Cloud Function deployment**: Always use `mktemp -d` for a temp directory when assembling deployment files. Set up a `trap` to clean up on exit. Only set generic env vars (e.g., `LOG_LEVEL`) in the function; credentials come per-request.

**Request-scoped credentials**: New Cloud Functions should accept optional `llm`, `search`, and `supabase` blocks in the HTTP payload and degrade gracefully when omitted (see `image_selection` module as the canonical example). For the full build checklist, see AGENTS.md → "Cloud Function Build Workflow (Image Selection Pattern)".

**Async job pattern**: On-demand modules that need async execution (e.g., `article_knowledge_extraction`) use a submit → poll → worker pattern: `/submit` enqueues a job and returns a `job_id`; `/poll` checks status; `/worker` executes the job. Jobs are stored in a Supabase table with atomic delete-on-read and a 24h TTL. A GitHub Actions cron workflow runs `cleanup_expired_jobs_cli.py` to sweep expired rows.

**Ephemeral content handoff** (`url_content_extraction`): Stage 2 (fetch) can optionally write extracted HTML bodies to `news_url_content_ephemeral`; stage 3 (facts) can read from there instead of re-fetching. Controlled by `EPHEMERAL_CONTENT_ENABLED` env var (default `false` in all workflows). Schema in `src/functions/url_content_extraction/schema.sql`. Sweep CLI at `scripts/ephemeral_sweep_cli.py`; a step in `content-pipeline-poll.yml` runs it unconditionally after each poll.

**Configuration**: All modules share a single `.env` at the project root. Load it with `load_env()` from `src.shared.utils.env`. Module-specific vars are documented in each module's `.env.example`.

## Key Reference Docs

- `AGENTS.md` — Coding conventions and architecture guidelines (read this)
- `docs/architecture/function_isolation.md` — Full isolation architecture details
- `docs/package_contract.md` — On-demand package request/response spec
- `docs/cloud_function_api.md` — HTTP API endpoints
- `src/functions/<module>/README.md` — Per-module CLI usage and deployment notes
