#!/bin/bash

# Firebase Cloud Function Deployment Script
# This script helps deploy the package_handler function to Google Cloud Functions (2nd gen)

set -e

# Configuration
FUNCTION_NAME="package-handler"
REGION="${REGION:-us-central1}"
RUNTIME="python312"
ENTRY_POINT="package_handler"
MEMORY="512Mi"
TIMEOUT="60s"
MAX_INSTANCES="10"
MIN_INSTANCES="0"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Helper functions
info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    error "gcloud CLI is not installed. Please install it from: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

# Check if user is authenticated
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
    error "You are not authenticated. Run: gcloud auth login"
    exit 1
fi

# Get current project
PROJECT_ID=$(gcloud config get-value project 2>/dev/null)
if [ -z "$PROJECT_ID" ]; then
    error "No GCP project set. Run: gcloud config set project YOUR_PROJECT_ID"
    exit 1
fi

info "Deploying to project: $PROJECT_ID"
info "Function name: $FUNCTION_NAME"
info "Region: $REGION"

# Navigate to functions directory
cd "$(dirname "$0")"

info "Deployment will include the entire src/ tree for proper imports"

# Navigate to PROJECT ROOT (4 levels up: functions -> data_loading -> functions -> src -> root)
cd ../../../..

info "Deploying from: $(pwd)"
info "This includes src/shared/ and src/functions/data_loading/"

# Check if .env.yaml exists in the functions directory
if [ -f "src/functions/data_loading/functions/.env.yaml" ]; then
    # Check if file has any uncommented non-empty lines
    if grep -q '^[^#]' src/functions/data_loading/functions/.env.yaml 2>/dev/null && grep -q ':' src/functions/data_loading/functions/.env.yaml 2>/dev/null; then
        info "Found .env.yaml - will include environment variables"
        ENV_FLAG="--env-vars-file=src/functions/data_loading/functions/.env.yaml"
    else
        warn ".env.yaml exists but appears to be empty or all commented"
        warn "Deploying without environment variables"
        ENV_FLAG=""
    fi
else
    warn "No .env.yaml found - deploying without environment variables"
    ENV_FLAG=""
fi

# Create temporary deployment directory
TEMP_DEPLOY_DIR=$(mktemp -d -t data-loading-deploy.XXXXXX)
info "Created temporary deployment directory: $TEMP_DEPLOY_DIR"

# Ensure cleanup happens even if deployment fails
cleanup() {
  if [ -d "$TEMP_DEPLOY_DIR" ]; then
    info "Cleaning up temporary deployment directory..."
    rm -rf "$TEMP_DEPLOY_DIR"
  fi
}
trap cleanup EXIT

# Copy entire src/ directory to temp location (exclude local virtualenvs/caches)
info "Copying source files to temporary directory..."
if command -v rsync >/dev/null 2>&1; then
  rsync -a \
    --exclude 'venv/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    src "$TEMP_DEPLOY_DIR/"
else
  cp -R src "$TEMP_DEPLOY_DIR/"
  rm -rf "$TEMP_DEPLOY_DIR/src/functions/data_loading/functions/venv" || true
fi

# Create temporary main.py in root that forwards to the real function module
info "Creating deployment entry point..."
cat > "$TEMP_DEPLOY_DIR/main.py" << 'EOF'
"""Deployment entry point for data_loading Cloud Function."""

from src.functions.data_loading.functions.main import package_handler
EOF

# Copy requirements.txt to temp deployment directory
info "Copying requirements.txt to deployment directory..."
cp src/functions/data_loading/functions/requirements.txt "$TEMP_DEPLOY_DIR/requirements.txt"

# Deploy the function from temporary directory
info "Starting deployment..."
info "Entry point: package_handler (via main.py)"
info "Source: $TEMP_DEPLOY_DIR (includes all of src/)"

gcloud functions deploy "$FUNCTION_NAME" \
    --gen2 \
    --runtime="$RUNTIME" \
    --region="$REGION" \
    --source="$TEMP_DEPLOY_DIR" \
    --entry-point="$ENTRY_POINT" \
    --trigger-http \
    --allow-unauthenticated \
    --memory="$MEMORY" \
    --timeout="$TIMEOUT" \
    --max-instances="$MAX_INSTANCES" \
    --min-instances="$MIN_INSTANCES" \
    $ENV_FLAG

DEPLOY_STATUS=$?

# Cleanup handled by trap

if [ $DEPLOY_STATUS -eq 0 ]; then
    info "Deployment successful!"
    info "Function URL:"
    gcloud functions describe "$FUNCTION_NAME" --region="$REGION" --gen2 --format="value(serviceConfig.uri)"
else
    error "Deployment failed!"
    exit 1
fi
