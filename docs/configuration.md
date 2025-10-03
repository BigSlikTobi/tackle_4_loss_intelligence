# Central Configuration Architecture

## Overview

This project uses a **single, centralized `.env` file** at the project root for all configuration. Individual function modules do NOT have their own `.env` files.

## Configuration File Location

```
/Users/tobiaslatta/Projects/temp/Tackle_4_loss_intelligence/.env
```

All function modules (`data_loading`, `news_extraction`, `content_summarization`) share this central configuration file.

## Benefits

1. **Single Source of Truth**: All credentials and configuration in one place
2. **No Duplication**: Shared variables (like `SUPABASE_URL`) only defined once
3. **Easier Maintenance**: Update credentials in one location
4. **Module Independence**: Modules can still be isolated while sharing configuration

## How It Works

### Automatic Discovery

The `load_env()` function from `src.shared.utils.env` automatically searches for `.env` files:

```python
from src.shared.utils.env import load_env

# Searches current directory and all parent directories for .env
load_env()
```

This means scripts can be run from any directory and will still find the central `.env`:

```bash
# Works from module directory
cd src/functions/content_summarization
python scripts/summarize_cli.py

# Also works from project root
cd /Users/tobiaslatta/Projects/temp/Tackle_4_loss_intelligence
python src/functions/content_summarization/scripts/summarize_cli.py
```

## Configuration Structure

The central `.env` file is organized by module:

```bash
# ============================================
# Shared Configuration (all modules)
# ============================================
SUPABASE_URL=https://yqtiuzhedkfacwgormhn.supabase.co
SUPABASE_KEY=eyJhbGciOi...
LOG_LEVEL=INFO

# ============================================
# Content Summarization Module
# ============================================
GEMINI_API_KEY=AIzaSyBC...
GEMINI_MODEL=gemini-2.5-flash
BATCH_SIZE=10
MAX_RETRIES=3
ENABLE_GROUNDING=false
MAX_REQUESTS_PER_MINUTE=60

# ============================================
# Data Loading Module
# ============================================
# (module-specific variables would go here)

# ============================================
# News Extraction Module  
# ============================================
# (module-specific variables would go here)
```

## Module-Specific vs. Shared Variables

### Shared Variables (All Modules)
- `SUPABASE_URL` - Database connection
- `SUPABASE_KEY` - Database authentication
- `LOG_LEVEL` - Logging verbosity

### Content Summarization Specific
- `GEMINI_API_KEY` - Google Gemini API key
- `GEMINI_MODEL` - Model selection
- `BATCH_SIZE` - Processing batch size
- `ENABLE_GROUNDING` - Search grounding toggle

### Data Loading Specific
- (Add as needed)

### News Extraction Specific
- (Add as needed)

## Security Best Practices

1. **Never commit `.env` to git**
   - Already in `.gitignore`
   - Contains sensitive credentials

2. **Use Secret Manager for production**
   - Cloud Functions: Use Secret Manager
   - Local dev: Use `.env` file

3. **Rotate keys regularly**
   - Update in one place (central `.env`)
   - All modules automatically use new values

## Cloud Function Deployment

When deploying to Cloud Functions, secrets are stored in Google Secret Manager and injected as environment variables:

```bash
gcloud functions deploy content-summarization \
  --set-secrets="GEMINI_API_KEY=GEMINI_API_KEY:latest,SUPABASE_URL=SUPABASE_URL:latest,SUPABASE_KEY=SUPABASE_KEY:latest"
```

This maintains the same variable names, ensuring consistency between local and production environments.

## Adding New Modules

When creating a new function module:

1. ✅ **DO NOT** create a module-specific `.env` file
2. ✅ **DO** add new variables to the central `.env` file
3. ✅ **DO** use `load_env()` from `src.shared.utils.env`
4. ✅ **DO** document your variables in comments within `.env`

Example:
```bash
# ============================================
# My New Module
# ============================================
MY_API_KEY=your-key-here
MY_SETTING=value
```

## Troubleshooting

### Variables not loading?

```bash
# Check central .env file exists
ls -la /Users/tobiaslatta/Projects/temp/Tackle_4_loss_intelligence/.env

# Check variable is defined
grep GEMINI_API_KEY /Users/tobiaslatta/Projects/temp/Tackle_4_loss_intelligence/.env

# Test loading
cd /Users/tobiaslatta/Projects/temp/Tackle_4_loss_intelligence
python -c "from src.shared.utils.env import load_env; load_env(); import os; print(os.getenv('GEMINI_API_KEY'))"
```

### Module can't find shared imports?

Make sure you're running from the project root or the Python path includes the project root:

```bash
cd /Users/tobiaslatta/Projects/temp/Tackle_4_loss_intelligence
python src/functions/content_summarization/scripts/summarize_cli.py
```

## Verification

Test that all modules can access the central configuration:

```bash
cd /Users/tobiaslatta/Projects/temp/Tackle_4_loss_intelligence

# Test content_summarization
python -c "import sys; sys.path.insert(0, '.'); from src.shared.utils.env import load_env; load_env(); import os; print('✓ GEMINI_API_KEY:', 'FOUND' if os.getenv('GEMINI_API_KEY') else 'MISSING')"

# Expected output: ✓ GEMINI_API_KEY: FOUND
```
