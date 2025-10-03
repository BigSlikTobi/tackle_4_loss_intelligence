# Function-Based Isolation Architecture

## Overview

This platform uses **function-based isolation** to separate different problem domains into independent, self-contained modules. Each functional module can be developed, tested, deployed, and deleted independently without affecting other modules.

## Architecture Principles

### 1. Complete Functional Isolation

Each function module is completely independent:

```
src/functions/
├── data_loading/          # Function 1: Data ingestion & packaging
│   ├── core/             # All business logic
│   ├── scripts/          # CLI tools
│   ├── functions/        # Cloud Function deployment
│   ├── tests/            # Unit tests
│   ├── requirements.txt  # Dependencies
│   └── README.md         # Documentation
│
└── news_extraction/       # Function 2: News URL extraction
    ├── core/             # All business logic
    ├── scripts/          # CLI tools
    ├── functions/        # Cloud Function deployment
    ├── tests/            # Unit tests
    ├── requirements.txt  # Dependencies
    └── README.md         # Documentation
```

**Key Point**: You can `rm -rf src/functions/data_loading` and `news_extraction` still works perfectly.

### 2. Minimal Shared Infrastructure

Only truly generic, reusable utilities are shared:

```
src/shared/
├── utils/
│   ├── logging.py        # Generic logging setup
│   └── env.py            # Environment variable loading
├── db/
│   └── connection.py     # Generic Supabase client creation
└── contracts/
    └── base.py           # Shared base contracts (optional)
```

**What's NOT shared:**
- Domain logic
- Data loaders/transformers
- Providers
- Pipelines
- Business-specific utilities

### 3. Independent Deployment

Each function module has its own Cloud Function deployment:

```bash
# Deploy data_loading only
cd src/functions/data_loading/functions
./deploy.sh

# Deploy news_extraction only
cd src/functions/news_extraction/functions
./deploy.sh
```

Deployed functions:
- `https://region-project.cloudfunctions.net/data-loader`
- `https://region-project.cloudfunctions.net/news-extractor`

### 4. Separate Dependencies

Each module manages its own dependencies:

**data_loading/requirements.txt**:
```
nflreadpy>=0.1.0
nfl-data-py>=0.3.0
pandas>=2.0.0
supabase>=2.0.0
```

**news_extraction/requirements.txt**:
```
beautifulsoup4>=4.12.0
requests>=2.31.0
lxml>=4.9.0
supabase>=2.0.0
```

No version conflicts between modules!

## Import Patterns

### Within a Function Module

Use relative imports to reference code within the same function:

```python
# In src/functions/data_loading/core/providers/pbp.py
from ..data.fetch import fetch_pbp_data
from ..data.transformers.game import GameTransformer
from ...core.pipelines import DatasetPipeline
```

### Using Shared Utilities

Use absolute imports for shared utilities:

```python
# In any function module
from src.shared.utils.logging import setup_logging
from src.shared.db import get_supabase_client
from src.shared.utils.env import get_required_env
```

### Between Function Modules

**DON'T DO THIS!** Function modules should never import from each other:

```python
# ❌ WRONG - Creates coupling
from src.functions.data_loading.core.providers import get_provider

# ✅ CORRECT - Each module is independent
# If you need similar functionality, implement it in each module
# or extract it to src/shared/ if truly generic
```

## Development Workflow

### Working on Data Loading

```bash
cd src/functions/data_loading

# Create isolated environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set up environment
cp .env.example .env
# Edit .env with your configuration

# Run scripts
python scripts/players_cli.py --dry-run

# Run tests
pytest tests/

# Deploy
cd functions
./deploy.sh
```

### Working on News Extraction

```bash
cd src/functions/news_extraction

# Completely separate environment
python -m venv venv
source venv/bin/activate

# Different dependencies
pip install -r requirements.txt

# Different configuration
cp .env.example .env
# Edit with news_extraction specific config

# Independent development
python scripts/extract_news_cli.py --source espn
```

## Testing Independence

### Verification Test

To verify modules are truly independent:

```bash
# Test 1: Delete data_loading
rm -rf src/functions/data_loading

# News extraction should still work
cd src/functions/news_extraction
python scripts/extract_news_cli.py

# Test 2: Restore data_loading, delete news_extraction
git checkout src/functions/data_loading
rm -rf src/functions/news_extraction

# Data loading should still work
cd src/functions/data_loading
python scripts/players_cli.py --dry-run
```

### Unit Testing

Each module has its own test suite:

```bash
# Test data_loading only
cd src/functions/data_loading
pytest tests/

# Test news_extraction only
cd src/functions/news_extraction
pytest tests/
```

## Configuration Management

### Environment Variables

Each function module has its own `.env` file:

**data_loading/.env**:
```bash
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-data-loading-key
LOG_LEVEL=INFO
```

**news_extraction/.env**:
```bash
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-news-extraction-key
LOG_LEVEL=DEBUG
ESPN_API_KEY=your-espn-key
```

Different functions can use:
- Different Supabase keys (different permissions)
- Different log levels
- Different configuration values

### Cloud Function Configuration

Each function has its own deployment configuration:

**data_loading/functions/.env.yaml**:
```yaml
SUPABASE_URL: "https://..."
SUPABASE_KEY: "production-data-loading-key"
LOG_LEVEL: "WARNING"
```

**news_extraction/functions/.env.yaml**:
```yaml
SUPABASE_URL: "https://..."
SUPABASE_KEY: "production-news-extraction-key"
LOG_LEVEL: "INFO"
ESPN_API_KEY: "production-espn-key"
```

## Benefits

### 1. Team Collaboration

Different teams can work on different functions without conflicts:

- **Team A**: Works on data_loading
- **Team B**: Works on news_extraction
- No merge conflicts in shared code
- Independent release cycles

### 2. Risk Mitigation

Bugs in one function don't affect others:

- Deploy data_loading update → news_extraction unaffected
- Data_loading has a bug → news_extraction still works
- Roll back data_loading → news_extraction continues running

### 3. Technology Flexibility

Each function can use different technologies:

- data_loading uses pandas
- news_extraction uses BeautifulSoup
- Future function could use different libraries
- No dependency conflicts

### 4. Scalability

Each function scales independently:

- data_loading gets heavy traffic → Scale it up
- news_extraction has light traffic → Keep it small
- Independent cost optimization
- Independent performance tuning

### 5. Maintenance

Easy to understand and maintain:

- Each function is self-contained
- Clear boundaries
- Easy to onboard new developers
- Can deprecate/remove functions easily

## Migration from Monolithic Structure

### Before (Monolithic)

```
src/
└── core/
    ├── data/
    ├── providers/
    ├── pipelines/
    └── utils/
```

All code in one place → tight coupling, hard to separate

### After (Function-Based Isolation)

```
src/
├── shared/           # Minimal shared code
└── functions/
    ├── data_loading/
    │   └── core/     # Everything for data_loading
    └── news_extraction/
        └── core/     # Everything for news_extraction
```

Clear boundaries → easy to maintain, test, deploy

## Best Practices

### DO

✅ Keep each function module completely self-contained  
✅ Use relative imports within a function module  
✅ Extract truly generic utilities to `src/shared/`  
✅ Give each function its own environment and dependencies  
✅ Write comprehensive README for each function module  
✅ Test each function module independently  

### DON'T

❌ Import between function modules  
❌ Share domain-specific logic in `src/shared/`  
❌ Create cross-function dependencies  
❌ Use same virtual environment for all functions  
❌ Deploy all functions together  
❌ Share configuration files between functions  

## Conclusion

Function-based isolation provides:

- **Independence**: Each module stands alone
- **Flexibility**: Different tech stacks, different teams
- **Safety**: Bugs don't cascade
- **Clarity**: Clear boundaries and responsibilities
- **Scalability**: Independent scaling and optimization

This architecture supports long-term maintainability and growth of the platform.
