# NFL Data Platform

**Independent functional modules** for NFL data processing. Each module is self-contained and can be developed, tested, and deployed separately.

---

## 📦 Functional Modules

### Data Loading
NFL data ingestion, transformation, and on-demand package assembly.

- **Location**: [`src/functions/data_loading/`](src/functions/data_loading/)
- **Status**: ✅ Production Ready
- **Features**: Warehouse datasets, on-demand packages, Cloud Function API, CLI tools

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

[**→ Full Documentation**](src/functions/news_extraction/README.md) | [**→ Deployment Guide**](src/functions/news_extraction/DEPLOYMENT.md)

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

# Deploy
cd functions && ./deploy.sh
```

### Content Summarization
AI-powered content summarization using Google Gemini with intelligent fallback strategies.

- **Location**: [`src/functions/content_summarization/`](src/functions/content_summarization/)
- **Status**: ✅ Production Ready
- **Features**: URL context analysis, multi-tier fallback, anti-hallucination prompts, rate limiting, circuit breaker, metrics collection

[**→ Full Documentation**](src/functions/content_summarization/README.md)

**Quick Start:**
```bash
cd src/functions/content_summarization
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Add to .env: GEMINI_API_KEY, GEMINI_MODEL

# Summarize URLs
python scripts/summarize_cli.py --dry-run --limit 5 --verbose
python scripts/summarize_cli.py --limit 10

# Deploy
cd functions && ./deploy.sh
```

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
│       │   ├── README.md          # Module documentation
│       │   └── DEPLOYMENT.md      # Testing & deployment guide
│       │
│       └── content_summarization/ # ✅ Production ready
│           ├── core/              # Business logic
│           │   ├── contracts/     # Data models
│           │   ├── db/            # Database operations (pagination, retry)
│           │   ├── llm/           # Gemini client + fallback fetcher
│           │   └── pipelines/     # Orchestration
│           ├── scripts/           # CLI tools
│           ├── functions/         # Cloud Function deployment
│           ├── requirements.txt   # Module dependencies
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

---

## 📚 Documentation

### Getting Started
1. **[README.md](README.md)** (this file) - Start here
2. **[Architecture & Design](docs/architecture/function_isolation.md)** - Understand the structure
3. **[Data Loading Module](src/functions/data_loading/README.md)** - NFL data ingestion & packages
4. **[News Extraction Module](src/functions/news_extraction/README.md)** - News URL extraction

### Module Documentation
- **[Data Loading README](src/functions/data_loading/README.md)** - Complete module documentation
- **[Data Loading Testing & Deployment](src/functions/data_loading/TESTING_DEPLOYMENT.md)** - Local testing & Cloud deployment
- **[News Extraction README](src/functions/news_extraction/README.md)** - Complete module documentation
- **[News Extraction Deployment](src/functions/news_extraction/DEPLOYMENT.md)** - Testing & deployment guide

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
├── README.md         # Module documentation
└── DEPLOYMENT.md     # Testing & deployment guide
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
- **Testing & Deployment**: Module-specific DEPLOYMENT.md files

---

**Built with function-based isolation for independence, scalability, and maintainability.** 🚀
