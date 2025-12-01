# NFL Data Platform

**Independent functional modules** for NFL data processing. Each module is self-contained and can be developed, tested, and deployed separately.

---

## 🧪 Testing

Install the lightweight dev dependencies and run the shared pytest suite from the project root:

```bash
python -m pip install -r requirements-dev.txt
pytest
```

Each module-specific test lives under `tests/<module_name>/` to respect function isolation. You can target a single module (for example, `pytest tests/story_embeddings`) when working locally.

## 📦 Functional Modules

### Data Loading
NFL data ingestion, transformation, and on-demand package assembly.

- **Location**: [`src/functions/data_loading/`](src/functions/data_loading/)
- **Status**: ✅ Production Ready
- **Features**: Warehouse datasets, on-demand packages, Cloud Function API, CLI tools, weekly injury reports (see README for schema/testing details)

[**→ Full Documentation**](src/functions/data_loading/README.md)

**Quick Start:**
```bash
cd src/functions/data_loading
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Configure Supabase

# Load data
python scripts/players_cli.py --dry-run
python scripts/games_cli.py --season 2024

# Load injury reports (see README "Injuries Loader")
python scripts/injuries_cli.py --season 2025 --week 6

# Test locally
cd functions && ./run_local.sh

# Deploy
./deploy.sh
```

### News Extraction
NFL news URL extraction from RSS feeds and sitemaps.

- **Location**: [`src/functions/news_extraction/`](src/functions/news_extraction/)
- **Status**: ✅ Production Ready
- **Features**: Concurrent extraction, HTTP caching, circuit breaker, comprehensive monitoring

[**→ Full Documentation (testing & deployment included)**](src/functions/news_extraction/README.md)

**Quick Start:**
```bash
cd src/functions/news_extraction
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Configure Supabase

# Extract news
python scripts/extract_news_cli.py --dry-run --verbose

# Production with metrics
python scripts/extract_news_cli.py --environment prod --metrics-file metrics.json

# Deploy (see README testing & deployment notes)
cd functions && ./deploy.sh
```

### Content Summarization
AI-powered content summarization using Google Gemini with intelligent fallback strategies.

- **Location**: [`src/functions/content_summarization/`](src/functions/content_summarization/)
- **Status**: ✅ Production Ready
- **Features**: Fact-first pipeline (facts → embeddings → summaries), Supabase edge queue integration, backlog processor with concurrency/heartbeats, rate limiting, circuit breaker, rich metrics

[**→ Full Documentation**](src/functions/content_summarization/README.md)

**Quick Start:**
```bash
cd src/functions/content_summarization
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Add to .env: GEMINI_API_KEY (plus optional overrides in README)

# Run fact→summary pipeline
python scripts/content_pipeline_cli.py --stage full --limit 20

# High-volume backlog run (see README for more flags)
python scripts/backlog_processor.py --stage facts --limit 1000 --prefetch-size 1000

# Deploy
cd functions && ./deploy.sh
```

### Story Embeddings
Vector embeddings for NFL news story summaries using OpenAI's text-embedding-3-small model.

- **Location**: [`src/functions/story_embeddings/`](src/functions/story_embeddings/)
- **Status**: ✅ Production Ready
- **Features**: Smart processing (LEFT JOIN for new summaries), timeout handling, rate limiting, error recovery, batch operations, cost tracking

[**→ Full Documentation**](src/functions/story_embeddings/README.md)

**Quick Start:**
```bash
cd src/functions/story_embeddings
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Add to .env: OPENAI_API_KEY

# Check progress
python scripts/generate_embeddings_cli.py --progress

# Test (no changes)
python scripts/generate_embeddings_cli.py --dry-run --limit 5

# Generate embeddings
python scripts/generate_embeddings_cli.py --limit 50 --verbose
```

### Story Grouping
Clusters similar NFL news stories based on embedding vectors using cosine similarity and centroid-based clustering.

- **Location**: [`src/functions/story_grouping/`](src/functions/story_grouping/)
- **Status**: ✅ Production Ready
- **Features**: Cosine similarity clustering, dynamic centroids, batch processing with pagination, dry-run mode, progress tracking

[**→ Full Documentation**](src/functions/story_grouping/README.md)

**Quick Start:**
```bash
cd src/functions/story_grouping
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Add to .env: SUPABASE_URL, SUPABASE_KEY, SIMILARITY_THRESHOLD

# Check progress
python scripts/group_stories_cli.py --progress

# Test (no changes)
python scripts/group_stories_cli.py --dry-run --limit 10

# Group stories
python scripts/group_stories_cli.py
```

### Knowledge Extraction
Extracts key topics and NFL entities from story groups using GPT-5-mini reasoning model with fuzzy entity matching.

- **Location**: [`src/functions/knowledge_extraction/`](src/functions/knowledge_extraction/)
- **Status**: ✅ Production Ready
- **Features**: GPT-5-mini with medium reasoning, fuzzy entity matching, retry logic, circuit breakers, batch processing, dry-run mode

[**→ Full Documentation**](src/functions/knowledge_extraction/README.md)

**Quick Start:**
```bash
cd src/functions/knowledge_extraction
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Add to .env: OPENAI_API_KEY

# Run schema.sql in Supabase SQL Editor

# Check progress
python scripts/extract_knowledge_cli.py --progress

# Test (no changes)
python scripts/extract_knowledge_cli.py --dry-run --limit 5

# Extract knowledge
python scripts/extract_knowledge_cli.py
```

---

## 🤖 Automated Content Pipeline

Fully automated GitHub Actions run every 30 minutes to move articles from raw URLs → content → facts → knowledge → summaries. The pipeline now runs as two coordinated workflows with strict gating and batch tracking to avoid duplicates.

### What Runs Where

- **content-pipeline-create.yml** (creator): Extracts URLs → fetches article content (Playwright) → submits OpenAI **facts** batch. Skips work when there are no new URLs unless `force_content_fetch` is set.
- **content-pipeline-poll.yml** (processor): Polls OpenAI batches, writes results, and promotes to the next stage using the `batch_jobs` tracking table to prevent overlap. Promotions require a minimum processed count (default `MIN_PROMOTION_ITEMS=100`):
  - Facts → Knowledge (topics)
  - Knowledge (topics) → Knowledge (entities)
  - Knowledge (entities) → Summaries

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    AUTOMATED CONTENT PIPELINE                               │
│                    Runs every 30 minutes (cron)                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  WORKFLOW 1: content-pipeline-create.yml ("creator")                │   │
│  ├─────────────────────────────────────────────────────────────────────┤   │
│  │  • Extract news URLs (days_back=1) → writes new URL IDs artifact    │   │
│  │  • Fetch article content with Playwright (10 workers, 45s timeout)  │   │
│  │    - Skips if no new URLs unless force_content_fetch=true           │   │
│  │  • Create facts batch (limit configurable, default 500)             │   │
│  │    - only validated articles, max age 48h, registers in Supabase    │   │
│  │    - OpenAI Batch API: async, ~24h, 50% cheaper                     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│                              ⬇️  Facts batch queued with OpenAI             │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  WORKFLOW 2: content-pipeline-poll.yml ("processor")                │   │
│  ├─────────────────────────────────────────────────────────────────────┤   │
│  │  • Polls batch_jobs table for pending batches and OpenAI status     │   │
│  │  • Processes completed batches and writes to Supabase               │   │
│  │  • Promotions (threshold-controlled):                               │   │
│  │      Facts → Knowledge (topics)                                     │   │
│  │      Topics → Knowledge (entities)                                  │   │
│  │      Entities → Summaries (with embeddings)                         │   │
│  │  • Retries processing failures; skips OpenAI-failed batches         │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Pipeline Stages Explained

| Stage | What It Does | How Long |
|-------|--------------|----------|
| **1. News Extraction** | Scans RSS/sitemaps for new NFL URLs; writes ID list artifact | ~30 seconds |
| **2. Content Fetching** | Fetches article HTML with Playwright (skips if no new URLs unless forced) | ~2–5 minutes |
| **3. Facts Extraction** | Submits OpenAI Batch API job for validated content (max age 48h, max 25 facts per URL) | Up to 24h* |
| **4. Knowledge (Topics → Entities)** | Sequential batches over facts; topics must meet threshold before entities | Up to 24h* each |
| **5. Summary Generation** | Generates summaries + embeddings from facts; promotes only when prior stage meets threshold | Up to 24h* |

*Batch API is ~50% cheaper; most complete sooner.

### Key Features

- **🔄 Cron + Concurrency Guards**: Both workflows scheduled every 30 minutes with non-canceling concurrency groups
- **🎯 Gated Promotions**: Next stage created only after thresholds (default `MIN_PROMOTION_ITEMS=100`)
- **📦 Batch Tracking**: `batch_jobs` table records stage, status, retry count, and OpenAI file IDs
- **💰 Batch API**: Uses OpenAI Batch for cost and queueing benefits
- **🔁 Safe Retries**: Retries processing failures; OpenAI-failed batches are left for manual re-creation
- **⚡ Smart Skips**: Content fetch and batch creation skip when no new work; `force_content_fetch` overrides

### Workflow Files

| File | Purpose |
|------|---------|
| [`.github/workflows/content-pipeline-create.yml`](.github/workflows/content-pipeline-create.yml) | Creates new batches (extract news → fetch content → create facts batch) |
| [`.github/workflows/content-pipeline-poll.yml`](.github/workflows/content-pipeline-poll.yml) | Polls and processes completed batches, creates next-stage batches |

### Required Secrets

Configure these in your GitHub repository settings (Settings → Secrets → Actions):

| Secret | Description |
|--------|-------------|
| `SUPABASE_URL` | Your Supabase project URL |
| `SUPABASE_KEY` | Your Supabase service role key |
| `OPENAI_API_KEY` | OpenAI API key for Batch API access |

### Manual Triggers

You can manually trigger either workflow from GitHub Actions:

```
GitHub → Actions → Content Pipeline - Create Batches → Run workflow
```

Optional inputs for manual runs:
- **Skip news extraction**: Jump straight to content fetching
- **Skip content fetch**: Only create facts batch
- **Force content fetch**: Run content fetch even when no new URLs were just inserted
- **Facts limit**: Control facts batch size (default: 20)
- **Poll: force check all**: Processor will re-check all pending batches

### Monitoring

Check workflow status in GitHub Actions. Each run shows:
- ✅ Steps completed successfully
- ❌ Steps that failed (with logs)
- ℹ️ Informational messages (e.g., "No new articles to process")

---

## 🏗️ Architecture

**Function-Based Isolation** - Each module operates independently:

```
T4L_data_loaders/
├── src/
│   ├── shared/                    # Minimal shared utilities
│   │   ├── utils/                 # Logging, environment loading
│   │   └── db/                    # Generic database helpers
│   │
│   └── functions/                 # Independent functional modules
│       ├── data_loading/          # ✅ Production ready
│       │   ├── core/              # Business logic (60+ files)
│       │   ├── scripts/           # CLI tools (8 scripts)
│       │   ├── functions/         # Cloud Function deployment
│       │   ├── requirements.txt   # Module dependencies
│       │   └── README.md          # Module documentation
│       │
│       ├── news_extraction/       # ✅ Production ready
│       │   ├── core/              # Business logic
│       │   │   ├── config/        # YAML configuration
│       │   │   ├── extractors/    # RSS/sitemap extractors
│       │   │   ├── pipelines/     # Orchestration
│       │   │   ├── processors/    # URL filtering
│       │   │   ├── data/          # Transformers
│       │   │   ├── db/            # Database writer
│       │   │   └── monitoring.py  # Metrics & logging
│       │   ├── scripts/           # CLI tools
│       │   ├── functions/         # Cloud Function deployment
│       │   ├── requirements.txt   # Module dependencies
│       │   └── README.md          # Module documentation
│       │
│       ├── content_summarization/ # ✅ Production ready
│       │   ├── core/              # Business logic
│       │   │   ├── contracts/     # Data models
│       │   │   ├── db/            # Database operations (pagination, retry)
│       │   │   ├── llm/           # Gemini client + fallback fetcher
│       │   │   └── pipelines/     # Orchestration
│       │   ├── scripts/           # CLI tools
│       │   ├── functions/         # Cloud Function deployment
│       │   ├── requirements.txt   # Module dependencies
│       │   └── README.md          # Module documentation
│       │
│       ├── story_embeddings/      # ✅ Production ready
│           ├── core/              # Business logic
│           │   ├── contracts/     # Data models (SummaryRecord, StoryEmbedding)
│           │   ├── db/            # Database operations (reader, writer)
│           │   ├── llm/           # OpenAI client with production features
│           │   └── pipelines/     # Orchestration pipeline
│           ├── scripts/           # CLI tools
│           ├── requirements.txt   # Module dependencies
│           ├── schema.sql         # Database schema
│           └── README.md          # Module documentation
│       │
│       ├── story_grouping/        # ✅ Production ready
│       │   ├── core/              # Business logic
│       │   │   ├── clustering/    # Similarity algorithms, grouping logic
│       │   │   ├── db/            # Database operations (with pagination)
│       │   │   └── pipelines/     # Orchestration pipeline
│       │   ├── scripts/           # CLI tools
│       │   ├── functions/         # Cloud Function deployment (future)
│       │   ├── requirements.txt   # Module dependencies
│       │   ├── schema.sql         # Database schema
│       │   └── README.md          # Module documentation
│       │
│       └── knowledge_extraction/  # ✅ Production ready
│           ├── core/              # Business logic
│           │   ├── db/            # Story reader, knowledge writer
│           │   ├── extraction/    # LLM extractors (GPT-5-mini)
│           │   ├── resolution/    # Fuzzy entity matching
│           │   └── pipelines/     # Orchestration pipeline
│           ├── scripts/           # CLI tools
│           ├── functions/         # Cloud Function deployment (future)
│           ├── requirements.txt   # Module dependencies
│           ├── schema.sql         # Database schema
│           └── README.md          # Module documentation
│
├── docs/                          # Documentation
├── requests/                      # Sample package requests
└── README.md                      # This file
```

**Key Principles:**
- ✅ **Complete Independence**: Delete one module → others still work
- ✅ **Isolated Dependencies**: Each module has its own `requirements.txt`
- ✅ **Separate Deployment**: Deploy functions independently
- ✅ **Minimal Shared Code**: Only generic utilities in `src/shared/`

**Import Patterns:**
```python
# Within a module (relative imports)
from ..data.fetch import fetch_data
from ...core.providers import Provider

# Shared utilities (absolute imports)
from src.shared.utils.logging import setup_logging
from src.shared.db import get_supabase_client

# ❌ Never import between function modules
# from src.functions.data_loading... in news_extraction
```

[**→ Architecture Details**](docs/architecture/function_isolation.md)

---

## 🚀 Getting Started

### Prerequisites
- Python 3.10+
- Supabase account
- Google Cloud account (for deployment)

### Shared Utilities

Available to all modules:

```python
from src.shared.utils.logging import setup_logging
from src.shared.db import get_supabase_client
from src.shared.utils.env import load_env
```

### Choose Your Module

Each module is independent:

- **Data Loading** → [`src/functions/data_loading/README.md`](src/functions/data_loading/README.md)
- **News Extraction** → [`src/functions/news_extraction/README.md`](src/functions/news_extraction/README.md)
- **Content Summarization** → [`src/functions/content_summarization/README.md`](src/functions/content_summarization/README.md)
- **Story Embeddings** → [`src/functions/story_embeddings/README.md`](src/functions/story_embeddings/README.md)
- **Story Grouping** → [`src/functions/story_grouping/README.md`](src/functions/story_grouping/README.md)
- **Knowledge Extraction** → [`src/functions/knowledge_extraction/README.md`](src/functions/knowledge_extraction/README.md)

---

## 📚 Documentation

### Getting Started
1. **[README.md](README.md)** (this file) - Start here
2. **[Architecture & Design](docs/architecture/function_isolation.md)** - Understand the structure
3. **[Data Loading Module](src/functions/data_loading/README.md)** - NFL data ingestion & packages
4. **[News Extraction Module](src/functions/news_extraction/README.md)** - News URL extraction
5. **[Content Summarization Module](src/functions/content_summarization/README.md)** - AI-powered summarization
6. **[Story Embeddings Module](src/functions/story_embeddings/README.md)** - Vector embeddings for similarity search
7. **[Story Grouping Module](src/functions/story_grouping/README.md)** - Clustering similar stories
8. **[Knowledge Extraction Module](src/functions/knowledge_extraction/README.md)** - Topic and entity extraction

### Module Documentation
- **[Data Loading README](src/functions/data_loading/README.md)** – Includes testing/deployment flow and the injuries loader reference
- **[News Extraction README](src/functions/news_extraction/README.md)** – Covers CLI usage plus testing & cloud deployment steps
- **[Content Summarization README](src/functions/content_summarization/README.md)** – Fact-first pipeline, backlog processor, knowledge/summary stages, and ops quick reference
- **[Story Embeddings README](src/functions/story_embeddings/README.md)** – Embedding pipeline details and tuning flags
- **[Story Grouping README](src/functions/story_grouping/README.md)** – Clustering algorithm, performance optimizations, schema
- **[Knowledge Extraction README](src/functions/knowledge_extraction/README.md)** – Topic/entity extraction, batch processing, schema

### Technical References
- **[Package Contract](docs/package_contract.md)** - On-demand package request/response spec
- **[Cloud Function API](docs/cloud_function_api.md)** - HTTP API & deployment architecture
- **[Architecture & Design Principles](docs/architecture/function_isolation.md)** - Function isolation pattern

### Development
- **[AI Agent Instructions](AGENTS.md)** - Development guidelines for AI assistants

---

## 🔧 Development Workflow

### Working on Data Loading

```bash
cd src/functions/data_loading

# Set up
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Edit with your config

# Develop & test
python scripts/players_cli.py --dry-run
cd functions && ./run_local.sh

# Deploy
./deploy.sh
```

### Adding New Modules

Follow the same pattern as existing modules:

```
src/functions/your_module/
├── core/              # Business logic
│   ├── config/       # Configuration
│   ├── data/         # Data processing
│   ├── db/           # Database operations
│   └── ...           # Module-specific logic
├── scripts/           # CLI tools
├── functions/         # Cloud Function deployment
│   ├── main.py       # Entry point
│   └── deploy.sh     # Deployment script
├── requirements.txt   # Module dependencies
├── .env.example      # Configuration template
└── README.md         # Module documentation (include testing & deployment notes)
```

See [function_isolation.md](docs/architecture/function_isolation.md) for details.

---

## 🔍 Troubleshooting

### Import Errors

**Problem**: `ModuleNotFoundError: No module named 'src'`

**Solution**: Make sure you're in the project root or set PYTHONPATH:
```bash
export PYTHONPATH="/path/to/T4L_data_loaders:$PYTHONPATH"
```

### Module Independence Test

Verify modules are truly independent:
```bash
# Test: data_loading works standalone
cd src/functions/data_loading
python scripts/players_cli.py --dry-run  # ✅ Should work

# Test: Delete one module, others still work
rm -rf src/functions/news_extraction
python scripts/players_cli.py --dry-run  # ✅ Still works!
```

---

## 🆘 Support

- **Architecture**: [docs/architecture/function_isolation.md](docs/architecture/function_isolation.md)
- **Data Loading**: [src/functions/data_loading/README.md](src/functions/data_loading/README.md)
- **News Extraction**: [src/functions/news_extraction/README.md](src/functions/news_extraction/README.md)
- **Content Summarization**: [src/functions/content_summarization/README.md](src/functions/content_summarization/README.md)
- **Story Embeddings**: [src/functions/story_embeddings/README.md](src/functions/story_embeddings/README.md)
- **Story Grouping**: [src/functions/story_grouping/README.md](src/functions/story_grouping/README.md)
- **Testing & Deployment**: Each module README now includes local testing and Cloud Function notes

---

**Built with function-based isolation for independence, scalability, and maintainability.** 🚀
