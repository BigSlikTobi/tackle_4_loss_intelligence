# Repository Guidelines

## Architecture: Function-Based Isolation

This platform uses **function-based isolation** to separate different problem domains into independent, self-contained modules.

### Core Principles
1. **Complete Independence**: Each function module can be deleted without affecting others
2. **Isolated Dependencies**: Each module has its own `requirements.txt` and virtualenv
3. **Separate Deployment**: Deploy functions independently to Cloud Functions
4. **Minimal Shared Code**: Only truly generic utilities live in `src/shared/`

### Directory Structure
```
src/
├── shared/                    # Minimal shared utilities ONLY
│   ├── utils/                 # Generic logging, env loading
│   └── db/                    # Generic database helpers
│
└── functions/                 # Independent functional modules
    ├── data_loading/          # Module 1: NFL data ingestion
    │   ├── core/              # Business logic (60+ files)
    │   ├── scripts/           # CLI tools (8 scripts)
    │   ├── functions/         # Cloud Function deployment
    │   ├── requirements.txt   # Module dependencies
    │   ├── .env.example       # Configuration template
    │   └── README.md          # Module documentation
    │
    └── news_extraction/       # Module 2: News URL extraction
        ├── core/              # Business logic
        ├── scripts/           # CLI tools
        ├── functions/         # Cloud Function deployment
        └── requirements.txt
```

### What Goes Where
- **`src/shared/`**: ONLY truly generic utilities (logging, db connection, env loading)
- **`src/functions/<module>/core/`**: ALL business logic for that module
- **`src/functions/<module>/scripts/`**: CLI tools for that module
- **`src/functions/<module>/functions/`**: Cloud Function deployment code
- ❌ **Never**: Import between function modules (creates coupling)

## Project Structure & Module Organization
## Project Structure & Module Organization

**Current Modules**:
- **data_loading**: Source in `src/functions/data_loading/core/`, split into `data` loaders/transformers, `db` connection helpers, `providers` for on-demand data, and `utils` for CLI/logging code
- Command-line entry points in `src/functions/data_loading/scripts/`; each script wraps a loader (e.g., `players_cli.py` maps to player data loader)
- On-demand accessors in `src/functions/data_loading/core/providers/`; e.g., `get_provider("pfr").list(season=2023, week=1)` returns weekly stats
- Package contract defined in `src/functions/data_loading/core/contracts/package.py` with usage in `docs/package_contract.md`
- Cloud Function in `src/functions/data_loading/functions/main.py` exposes package assembly as HTTP API (see `docs/cloud_function_api.md`)
- Each module has its own virtualenv in `venv/`; keep it local and out of commits. Dependencies in each module's `requirements.txt`

**Import Patterns**:
```python
# Within a module (relative imports)
from ..data.fetch import fetch_data
from ...core.providers import Provider

# Shared utilities (absolute imports)
from src.shared.utils.logging import setup_logging
from src.shared.db import get_supabase_client

# ❌ NEVER import between function modules
# from src.functions.data_loading... in news_extraction
```

## Build, Test, and Development Commands

**Per-Module Setup** (each module is independent):
```bash
# Navigate to specific module
cd src/functions/data_loading  # or news_extraction

# Create isolated environment
python -m venv venv && source venv/bin/activate

# Install module dependencies
pip install -r requirements.txt

# Configure module
cp .env.example .env  # Edit with module-specific config
```

**Data Loading Module Commands**:
- Dry-run a loader: `cd src/functions/data_loading && python scripts/players_cli.py --dry-run`
- Real load with diagnostics: `python scripts/games_cli.py --clear --verbose`
- Assemble packages: `python scripts/package_cli.py --request ../../../requests/player_weekly_stats_package.json --pretty`
- Test locally: `cd functions && ./run_local.sh`
- Deploy: `cd functions && ./deploy.sh`

**Debugging**:
- Enable debug logging: `export LOG_LEVEL=DEBUG` before invoking scripts
- Test module independence: Delete one module and verify others still work

## Coding Style & Naming Conventions

- Follow PEP 8 with four-space indentation, descriptive snake_case names, and consistent type hints
- **Module-specific code**: Place in `src/functions/<module>/core/` - never in `src/shared/`
- **Shared utilities**: Only truly generic code (logging, db, env) goes in `src/shared/`
- Use relative imports within a module: `from ..data.fetch import fetch_data`
- Use absolute imports for shared utilities: `from src.shared.utils.logging import setup_logging`
- Keep loader classes and transformers small; place shared logic in module's `core/utils/` or `core/data/transformers/`
- Module docstrings should explain intent; prefer f-strings for formatting and structured dict results for outputs
- Each module follows the same structure: `core/`, `scripts/`, `functions/`, `requirements.txt`, `.env.example`, `README.md`

**Adding New Functionality**:
- **Module-specific**: Add to `src/functions/<module>/core/`
- **Truly generic** (logging, db): Add to `src/shared/`
- **New problem domain**: Create new module in `src/functions/<new_module>/`

## Testing Guidelines

- No automated test suite exists yet
- For manual verification: 
  - Run loaders with `--dry-run` and confirm record counts
  - Test module independence: `rm -rf src/functions/<module>` and verify others work
  - Test locally: `cd src/functions/data_loading/functions && ./run_local.sh`

## Architecture Guidelines

**When Creating New Code**:
1. **Determine scope**: Is it module-specific or truly generic?
2. **Module-specific** → `src/functions/<module>/core/`
3. **Truly generic** (logging, db, env) → `src/shared/`
4. **New domain** → `src/functions/<new_module>/` (copy structure from existing module)

**Never**:
- ❌ Import between function modules (creates coupling)
- ❌ Put module-specific logic in `src/shared/`
- ❌ Share dependencies between modules (each has own `requirements.txt`)

**Verification**:
- Can you delete one module without breaking others? ✅
- Does each module have its own dependencies? ✅
- Can modules be deployed independently? ✅

See `docs/architecture/function_isolation.md` for complete architecture documentation.

## Commit & Pull Request Guidelines

- No repository exists yet

## Security & Configuration Tips

- All modules share a **central `.env` file** at project root (no module-specific `.env` files)
- Never hard-code secrets; load credentials from the central `.env` using `load_env()` from `src.shared.utils.env`
- Configuration: Add module-specific variables to the central `.env` file with clear section comments
- Required for all modules: `SUPABASE_URL`, `SUPABASE_KEY` in central `.env`
- When sharing scripts or notebooks, redact API responses and confirm logging stays at `INFO` or lower
- See `docs/configuration.md` for detailed configuration architecture

## Quick Reference

**Architecture**: `docs/architecture/function_isolation.md`  
**Module Documentation**: `src/functions/<module>/README.md`  
**API Documentation**: `docs/cloud_function_api.md`  
**Package Contract**: `docs/package_contract.md`  

**Key Paths**:
- Shared utilities: `src/shared/`
- Data loading: `src/functions/data_loading/`
- News extraction: `src/functions/news_extraction/`
