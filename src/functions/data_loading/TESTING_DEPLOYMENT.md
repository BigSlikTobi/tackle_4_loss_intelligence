# Testing & Deployment Guide for Data Loading Function

## 🧪 Testing Locally (Recommended First)

### Option 1: Test with run_local.sh (Recommended)

```bash
cd src/functions/data_loading/functions
./run_local.sh
```

This will:
- ✅ Create/activate a virtual environment
- ✅ Install dependencies
- ✅ Set PYTHONPATH to include project root
- ✅ Load environment variables from `../.env`
- ✅ Start the function on http://localhost:8080

**In another terminal, test it:**
```bash
cd src/functions/data_loading/functions
./test_function.sh
```

### Option 2: Manual Testing

```bash
# From project root
cd src/functions/data_loading

# Set up environment
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Set PYTHONPATH
export PYTHONPATH="/Users/tobiaslatta/Projects/temp/T4L_data_loaders:$PYTHONPATH"

# Load environment
cp .env.example .env
# Edit .env with your Supabase credentials
source .env

# Run functions-framework
cd functions
functions-framework --target=package_handler --source=. --port=8080 --debug
```

**Test with curl:**
```bash
curl -X POST http://localhost:8080 \
  -H "Content-Type: application/json" \
  -d @../../../requests/player_weekly_stats_package.json
```

## 🚀 Deploying to Cloud Functions

### Step 1: Prepare Environment Variables

Create `.env.yaml` in `src/functions/data_loading/functions/`:

```yaml
# src/functions/data_loading/functions/.env.yaml
SUPABASE_URL: "https://your-project.supabase.co"
SUPABASE_KEY: "your-production-service-role-key"
LOG_LEVEL: "INFO"
```

⚠️ **Important**: Add this file to `.gitignore` - it contains secrets!

### Step 2: Check Requirements

```bash
cd src/functions/data_loading/functions
./check_requirements.sh
```

This verifies:
- ✅ gcloud CLI is installed
- ✅ You're authenticated
- ✅ GCP project is set
- ✅ Required APIs are enabled

### Step 3: Deploy

```bash
cd src/functions/data_loading/functions
./deploy.sh
```

This will:
1. Navigate to project root
2. Create a temporary `main.py` entry point
3. Deploy with `--source=.` (includes all of `src/`)
4. Clean up temporary files
5. Display the function URL

**What gets deployed:**
- ✅ `src/shared/` - Shared utilities
- ✅ `src/functions/data_loading/core/` - All business logic
- ✅ `src/functions/data_loading/functions/main.py` - Entry point
- ❌ `src/functions/news_extraction/` - Excluded
- ❌ `scripts/` - Excluded (not needed in Cloud Function)
- ❌ `tests/` - Excluded
- ❌ `docs/` - Excluded

## 🔍 Troubleshooting

### Local Testing Issues

#### ImportError: cannot import name 'assemble_package'

**Cause**: PYTHONPATH not set correctly

**Fix**: The updated `run_local.sh` sets this automatically. If running manually:
```bash
export PYTHONPATH="/path/to/T4L_data_loaders:$PYTHONPATH"
```

#### ModuleNotFoundError: No module named 'src'

**Cause**: Running from wrong directory

**Fix**: Either:
- Use `./run_local.sh` (handles this automatically)
- Or run from project root with PYTHONPATH set

#### functions-framework not found

**Cause**: Not in virtual environment or not installed

**Fix**:
```bash
source venv/bin/activate
pip install functions-framework
```

### Deployment Issues

#### Import errors in Cloud Function

**Cause**: The deployment didn't include the full `src/` tree

**Fix**: 
- Ensure you're using the updated `deploy.sh`
- It should deploy from project root with `--source=.`
- Check `.gcloudignore` isn't excluding needed files

#### Environment variables not set

**Cause**: `.env.yaml` not found or malformed

**Fix**:
- Create `src/functions/data_loading/functions/.env.yaml`
- Ensure proper YAML syntax (key: "value")
- Check deployment logs for environment variable warnings

#### Deployment succeeds but function fails

**Cause**: Runtime errors (usually imports or missing dependencies)

**Fix**:
1. Check Cloud Function logs:
   ```bash
   gcloud functions logs read package-handler --region=us-central1 --limit=50
   ```

2. Test locally first with `./run_local.sh`

3. Verify all dependencies in `requirements.txt`

## 📊 Comparing Old vs New Structure

### Old Structure (Broken after migration)
```
# Deployed from project root
main.py  # At root, imports from src.core
functions/
  deploy.sh  # Deployed from root
  
# Imports:
from src.core.packaging import assemble_package  # ✅ Worked
```

### New Structure (Current)
```
# Deploy from project root with entry point wrapper
src/
  functions/
    data_loading/
      functions/
        main.py  # Uses relative imports
        deploy.sh  # Creates root main.py wrapper
        
# Imports in functions/main.py:
from ...core.packaging import assemble_package  # ✅ Works with PYTHONPATH

# Created at deploy time (root main.py):
from src.functions.data_loading.functions.main import package_handler  # ✅ Works in Cloud
```

## ✅ Recommended Testing Flow

1. **Local Testing First**
   ```bash
   cd src/functions/data_loading/functions
   ./run_local.sh
   # In another terminal:
   ./test_function.sh
   ```

2. **Fix Any Issues Locally**
   - Adjust imports if needed
   - Verify environment variables
   - Test with sample requests

3. **Deploy to Cloud Functions**
   ```bash
   ./check_requirements.sh  # Verify GCP setup
   ./deploy.sh              # Deploy
   ```

4. **Test Deployed Function**
   ```bash
   # Get function URL
   gcloud functions describe package-handler --region=us-central1 --gen2 --format="value(serviceConfig.uri)"
   
   # Test it
   curl -X POST <FUNCTION_URL> \
     -H "Content-Type: application/json" \
     -d @../../../requests/player_weekly_stats_package.json
   ```

5. **Monitor Logs**
   ```bash
   gcloud functions logs read package-handler --region=us-central1 --limit=50
   ```

## 🎯 Summary

**Do you need to redeploy?** 

- **Yes**, because the structure changed from `src.core.*` to `src.functions.data_loading.core.*`
- But **test locally first** with the updated `run_local.sh` script
- The deployment script has been updated to handle the new structure

**Testing Workflow:**
1. ✅ Local test: `./run_local.sh` (quick, no costs)
2. ✅ Fix any issues
3. ✅ Deploy: `./deploy.sh` (once it works locally)
4. ✅ Monitor deployed function

Both scripts have been updated to work with the new function-based isolation architecture! 🎉
