# Testing & Deployment Guide for News Extraction Function

## 🧪 Testing Locally

### Quick Test with CLI

```bash
cd src/functions/news_extraction

# Set up environment (first time only)
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Edit with your Supabase credentials

# Run tests
python scripts/extract_news_cli.py --dry-run --max-articles 2 --verbose
python scripts/extract_news_cli.py --dry-run --metrics-file test_metrics.json --pretty
```

### Testing Production Configuration

```bash
# Test with production settings
python scripts/extract_news_cli.py \
  --environment prod \
  --max-workers 6 \
  --timeout 20 \
  --output-format json \
  --metrics-file metrics.json \
  --dry-run \
  --verbose
```

**Expected Output:**
- ✅ Concurrent processing of 4+ sources
- ✅ HTTP caching logs ("Cached response for...")
- ✅ Success rate: 100%
- ✅ Throughput: 20+ items/second
- ✅ Structured JSON metrics

### Manual Testing with Python

```bash
cd src/functions/news_extraction
source venv/bin/activate

# Set PYTHONPATH
export PYTHONPATH="/path/to/T4L_data_loaders:$PYTHONPATH"

# Load environment
source .env

# Test extraction directly
python -c "
from core.pipelines.news_pipeline import NewsPipeline
from core.config.loader import load_config

config = load_config()
pipeline = NewsPipeline(config)
result = pipeline.run(dry_run=True)
print(f'Extracted {result[\"items_extracted\"]} items')
"
```

## 🚀 Deploying to Cloud Functions

### Step 1: Prepare Environment Variables

Create `.env.yaml` in `src/functions/news_extraction/functions/`:

```yaml
# src/functions/news_extraction/functions/.env.yaml
SUPABASE_URL: "https://your-project.supabase.co"
SUPABASE_KEY: "your-production-service-role-key"
LOG_LEVEL: "INFO"
```

⚠️ **Important**: Add this file to `.gitignore` - it contains secrets!

### Step 2: Create Deployment Scripts

Create `functions/deploy.sh`:

```bash
#!/bin/bash
# src/functions/news_extraction/functions/deploy.sh

set -e

FUNCTION_NAME="news-extraction"
REGION="us-central1"
RUNTIME="python310"
MEMORY="512MB"
TIMEOUT="540s"
ENTRY_POINT="extract_news"

echo "🚀 Deploying $FUNCTION_NAME to Cloud Functions..."

# Check we're in the right directory
if [ ! -f "main.py" ]; then
    echo "❌ Error: main.py not found. Run this script from functions/ directory."
    exit 1
fi

# Check .env.yaml exists
if [ ! -f ".env.yaml" ]; then
    echo "❌ Error: .env.yaml not found. Please create it with your Supabase credentials."
    echo "   See .env.example for reference."
    exit 1
fi

# Navigate to project root for deployment
cd ../../../..

# Deploy with full source tree
gcloud functions deploy $FUNCTION_NAME \
  --gen2 \
  --runtime=$RUNTIME \
  --region=$REGION \
  --source=. \
  --entry-point=$ENTRY_POINT \
  --trigger-http \
  --allow-unauthenticated \
  --memory=$MEMORY \
  --timeout=$TIMEOUT \
  --env-vars-file=src/functions/news_extraction/functions/.env.yaml \
  --set-env-vars=PYTHONPATH=/workspace/src

echo "✅ Deployment complete!"
echo ""
echo "Function URL:"
gcloud functions describe $FUNCTION_NAME --region=$REGION --gen2 --format="value(serviceConfig.uri)"
```

Make it executable:
```bash
chmod +x functions/deploy.sh
```

### Step 3: Create Cloud Function Entry Point

Create `functions/main.py`:

```python
"""
Cloud Function entry point for news extraction.
"""
from src.functions.news_extraction.core.pipelines.news_pipeline import NewsPipeline
from src.functions.news_extraction.core.config.loader import load_config
from src.shared.utils.logging import setup_logging
import json

def extract_news(request):
    """
    HTTP Cloud Function entry point.
    
    Args:
        request: Flask request object
        
    Returns:
        JSON response with extraction results
    """
    setup_logging()
    
    try:
        # Parse request
        request_json = request.get_json(silent=True) or {}
        
        # Load configuration
        config = load_config()
        
        # Create and run pipeline
        pipeline = NewsPipeline(config)
        result = pipeline.run(
            source_filter=request_json.get('source'),
            days_back=request_json.get('days_back'),
            max_articles=request_json.get('max_articles')
        )
        
        return json.dumps(result), 200, {'Content-Type': 'application/json'}
        
    except Exception as e:
        error_response = {
            'success': False,
            'error': str(e)
        }
        return json.dumps(error_response), 500, {'Content-Type': 'application/json'}
```

### Step 4: Deploy

```bash
cd src/functions/news_extraction/functions
./deploy.sh
```

**What gets deployed:**
- ✅ `src/shared/` - Shared utilities
- ✅ `src/functions/news_extraction/core/` - All business logic
- ✅ `src/functions/news_extraction/functions/main.py` - Entry point
- ❌ `src/functions/data_loading/` - Excluded
- ❌ `scripts/` - Excluded (not needed in Cloud Function)
- ❌ `tests/` - Excluded

## 🔍 Testing Deployed Function

### Get Function URL

```bash
gcloud functions describe news-extraction \
  --region=us-central1 \
  --gen2 \
  --format="value(serviceConfig.uri)"
```

### Test with curl

```bash
# Extract from all sources
curl -X POST <FUNCTION_URL> \
  -H "Content-Type: application/json" \
  -d '{}'

# Extract from specific source
curl -X POST <FUNCTION_URL> \
  -H "Content-Type: application/json" \
  -d '{"source": "ESPN", "max_articles": 10}'

# Filter by recency
curl -X POST <FUNCTION_URL> \
  -H "Content-Type: application/json" \
  -d '{"days_back": 7}'
```

### Monitor Logs

```bash
# View recent logs
gcloud functions logs read news-extraction \
  --region=us-central1 \
  --limit=50

# Follow logs in real-time
gcloud functions logs read news-extraction \
  --region=us-central1 \
  --limit=50 \
  --follow
```

## 🛠️ Troubleshooting

### Local Testing Issues

#### ImportError: No module named 'src'

**Cause**: PYTHONPATH not set correctly

**Fix**: Set PYTHONPATH from project root:
```bash
export PYTHONPATH="/path/to/T4L_data_loaders:$PYTHONPATH"
```

#### Database Connection Issues

**Cause**: Invalid Supabase credentials in `.env`

**Fix**: Verify credentials:
```bash
cat .env | grep SUPABASE

# Test connection
python -c "from src.shared.db import get_supabase_client; print(get_supabase_client())"
```

#### HTTP Timeout Errors

**Cause**: Network issues or slow sources

**Fix**: Increase timeout in config or CLI:
```bash
python scripts/extract_news_cli.py --timeout 30 --verbose
```

### Deployment Issues

#### gcloud command not found

**Cause**: Google Cloud SDK not installed

**Fix**: Install gcloud CLI:
```bash
# macOS
brew install google-cloud-sdk

# Or download from: https://cloud.google.com/sdk/docs/install
```

#### Deployment fails with import errors

**Cause**: Missing dependencies or incorrect source path

**Fix**:
1. Verify `requirements.txt` is complete:
   ```bash
   cat functions/requirements.txt
   ```

2. Ensure deployment from project root with `--source=.`

3. Check `.gcloudignore` isn't excluding needed files

#### Function deployed but returns 500 errors

**Cause**: Runtime errors (check logs)

**Fix**:
```bash
# View detailed logs
gcloud functions logs read news-extraction --region=us-central1 --limit=100

# Common issues:
# - Missing environment variables in .env.yaml
# - Import errors (verify PYTHONPATH)
# - Database connection issues (verify credentials)
```

### Performance Issues

#### Slow extraction (>5 seconds)

**Solutions**:
- Increase workers in request: `{"max_workers": 8}`
- Reduce timeout: `{"timeout": 10}`
- Limit articles: `{"max_articles": 20}`
- Check HTTP cache effectiveness in logs

#### High memory usage

**Solutions**:
- Reduce `max_articles` per source
- Check for memory leaks in custom extractors
- Increase Cloud Function memory: `--memory=1GB`

## 📊 Performance Benchmarks

### Expected Performance (4 sources, ~20 items)

**Local Testing:**
- Duration: 0.9-1.5s
- Throughput: 15-25 items/second
- Memory: ~100MB
- Success rate: 100%

**Cloud Function (Cold Start):**
- First request: 2-4s (includes initialization)
- Subsequent: 1-2s
- Memory: 200-300MB
- Timeout: Set to 540s (9 min) for safety

**Cloud Function (Warm):**
- Duration: 1-2s
- Throughput: 15-20 items/second
- Success rate: >99%

### Optimization Tips

1. **HTTP Caching**: 300s TTL saves ~50% of requests
2. **Concurrent Processing**: 4-6 workers optimal for most cases
3. **Batch Database Writes**: Reduces Supabase API calls
4. **Circuit Breaker**: Prevents wasted retries on failing sources

## ✅ Recommended Testing Flow

1. **Local CLI Testing**
   ```bash
   # Quick validation
   python scripts/extract_news_cli.py --dry-run --max-articles 2 --verbose
   
   # Full metrics test
   python scripts/extract_news_cli.py --dry-run --metrics-file test.json --pretty
   ```

2. **Production Config Testing**
   ```bash
   # Test with production settings (dry-run)
   python scripts/extract_news_cli.py \
     --environment prod \
     --max-workers 6 \
     --output-format json \
     --dry-run
   ```

3. **Real Extraction Test**
   ```bash
   # Small test batch
   python scripts/extract_news_cli.py --max-articles 5 --verbose
   
   # Verify in Supabase
   ```

4. **Deploy to Cloud Functions**
   ```bash
   cd functions
   ./deploy.sh
   ```

5. **Test Deployed Function**
   ```bash
   # Get URL
   FUNCTION_URL=$(gcloud functions describe news-extraction \
     --region=us-central1 --gen2 --format="value(serviceConfig.uri)")
   
   # Test
   curl -X POST $FUNCTION_URL -H "Content-Type: application/json" -d '{}'
   ```

6. **Monitor Production**
   ```bash
   # Watch logs
   gcloud functions logs read news-extraction --region=us-central1 --follow
   ```

## 🎯 Production Checklist

Before deploying to production:

- [ ] Tested locally with `--dry-run` and `--verbose`
- [ ] Verified metrics show 100% success rate
- [ ] Tested with production configuration (`--environment prod`)
- [ ] Created `.env.yaml` with production credentials
- [ ] Verified `.env.yaml` is in `.gitignore`
- [ ] Reviewed Cloud Function logs for errors
- [ ] Tested deployed function with sample requests
- [ ] Set up monitoring/alerting for failures
- [ ] Documented any custom configuration changes
- [ ] Verified database has proper indexes on `news_urls` table

## 📚 Additional Resources

- **[README.md](README.md)** - Module overview and CLI usage
- **[Architecture](../../../docs/architecture/function_isolation.md)** - Function isolation pattern
- **[Google Cloud Functions Docs](https://cloud.google.com/functions/docs)** - Official documentation

---

**Ready for production deployment with comprehensive testing workflow!** 🚀
