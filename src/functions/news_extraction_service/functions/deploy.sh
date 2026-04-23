#!/bin/bash
# Deployment script for news_extraction_service.
#
# Deploys three entry points from a single source zip:
#   - news-extraction-worker  (run_news_extraction_worker)
#   - news-extraction-poll    (poll_news_extraction_job)
#   - news-extraction-submit  (submit_news_extraction_job)
#
# Worker is deployed first so we can capture its URL and pass it to submit
# as WORKER_URL. A shared secret (WORKER_TOKEN) is passed to both submit and
# worker via env vars; rotate by re-running the script with a new token.

set -e

REGION="${REGION:-us-central1}"
RUNTIME="python312"
MEMORY="${MEMORY:-512MB}"
TIMEOUT="${TIMEOUT:-540s}"
LOG_LEVEL_ENV="${LOG_LEVEL:-INFO}"

SUBMIT_FN="news-extraction-submit"
POLL_FN="news-extraction-poll"
WORKER_FN="news-extraction-worker"

SUBMIT_ENTRY="submit_news_extraction_job"
POLL_ENTRY="poll_news_extraction_job"
WORKER_ENTRY="run_news_extraction_worker"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

cd "$(dirname "$0")"

if ! command -v gcloud >/dev/null 2>&1; then
  error "gcloud CLI not found. Install the Cloud SDK first."
  exit 1
fi
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>/dev/null | grep -q .; then
  error "No active gcloud account. Run 'gcloud auth login' first."
  exit 1
fi
PROJECT_ID=$(gcloud config get-value project 2>/dev/null)
if [ -z "$PROJECT_ID" ]; then
  error "No GCP project configured. Run 'gcloud config set project PROJECT_ID' first."
  exit 1
fi

if [ -z "$WORKER_TOKEN" ]; then
  WORKER_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
  warn "WORKER_TOKEN not provided — generated a fresh one. Save this value!"
  echo "     WORKER_TOKEN=$WORKER_TOKEN"
fi

# Move to project root.
cd ../../../..

TEMP_DEPLOY_DIR=$(mktemp -d -t news-svc-deploy.XXXXXX)
info "Created temporary deployment directory: $TEMP_DEPLOY_DIR"
cleanup() {
  if [ -d "$TEMP_DEPLOY_DIR" ]; then
    info "Cleaning up temporary deployment directory..."
    rm -rf "$TEMP_DEPLOY_DIR"
  fi
}
trap cleanup EXIT

info "Copying source files..."
rsync -a \
  --exclude 'venv/' --exclude '.venv/' \
  --exclude '__pycache__/' --exclude '*.pyc' \
  --exclude '.env' --exclude '.env.local' \
  --exclude '.pytest_cache/' --exclude '.mypy_cache/' \
  src/ "$TEMP_DEPLOY_DIR/src/"

info "Writing Cloud Function entry points..."
cat > "$TEMP_DEPLOY_DIR/main.py" <<'EOF'
"""Deployment entry points for news_extraction_service."""

from __future__ import annotations

import flask

from src.functions.news_extraction_service.functions.main import (
    health_check_handler,
    poll_handler,
    submit_handler,
    worker_handler,
)


def submit_news_extraction_job(request: flask.Request):
    return submit_handler(request)


def poll_news_extraction_job(request: flask.Request):
    return poll_handler(request)


def run_news_extraction_worker(request: flask.Request):
    return worker_handler(request)


def health_check(request: flask.Request):
    return health_check_handler(request)
EOF

info "Writing deployment requirements.txt..."
cat > "$TEMP_DEPLOY_DIR/requirements.txt" <<'EOF'
functions-framework==3.*
flask==3.*
beautifulsoup4>=4.12
feedparser>=6.0
httpx>=0.27
lxml>=5.1
pydantic>=2.9
PyYAML>=6.0
supabase>=2.10
requests>=2.32
postgrest>=0.10
python-dotenv>=1.0.0
EOF

deploy_fn() {
  local name="$1"
  local entry="$2"
  shift 2
  info "Deploying $name (entry=$entry)..."
  gcloud functions deploy "$name" \
    --gen2 \
    --region="$REGION" \
    --runtime="$RUNTIME" \
    --entry-point="$entry" \
    --trigger-http \
    --allow-unauthenticated \
    --memory="$MEMORY" \
    --timeout="$TIMEOUT" \
    --source="$TEMP_DEPLOY_DIR" \
    "$@"
}

fn_url() {
  gcloud functions describe "$1" --region="$REGION" --gen2 --format="value(serviceConfig.uri)"
}

# 1. Worker first.
deploy_fn "$WORKER_FN" "$WORKER_ENTRY" \
  --set-env-vars="LOG_LEVEL=${LOG_LEVEL_ENV},WORKER_TOKEN=${WORKER_TOKEN}" \
  --clear-secrets

WORKER_URL=$(fn_url "$WORKER_FN")
if [ -z "$WORKER_URL" ]; then
  error "Could not read worker URL after deploy."
  exit 1
fi
info "Worker URL: $WORKER_URL"

# 2. Poll (no worker dep).
deploy_fn "$POLL_FN" "$POLL_ENTRY" \
  --set-env-vars="LOG_LEVEL=${LOG_LEVEL_ENV}" \
  --clear-secrets

# 3. Submit, with WORKER_URL + WORKER_TOKEN wired in.
deploy_fn "$SUBMIT_FN" "$SUBMIT_ENTRY" \
  --set-env-vars="LOG_LEVEL=${LOG_LEVEL_ENV},WORKER_URL=${WORKER_URL},WORKER_TOKEN=${WORKER_TOKEN}" \
  --clear-secrets

echo ""
info "✓ Deployment complete!"
echo ""
echo "  Submit:  $(fn_url "$SUBMIT_FN")"
echo "  Poll:    $(fn_url "$POLL_FN")"
echo "  Worker:  $WORKER_URL"
echo ""
warn "Remember: set WORKER_TOKEN=$WORKER_TOKEN in the cleanup cron secrets."
