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

# Copy entire src/ directory to temp location
info "Copying source files to temporary directory..."
cp -r src "$TEMP_DEPLOY_DIR/"

# Create temporary main.py in root that imports from the correct location
info "Creating deployment entry point..."
cat > "$TEMP_DEPLOY_DIR/main.py" << 'EOF'
"""Deployment entry point for data_loading Cloud Function."""

from __future__ import annotations
import json
import logging
from typing import Any
import flask

from src.functions.data_loading.core.packaging import assemble_package


def package_handler(request: flask.Request) -> flask.Response:
    """HTTP Cloud Function entry point for package assembly.
    
    Args:
        request: Flask request object
        
    Returns:
        Flask response with assembled package or error message
    """
    # Handle CORS preflight
    if request.method == "OPTIONS":
        return _cors_response({}, status=204)

    # Only accept POST requests
    if request.method != "POST":
        return _error_response("Only POST requests are supported", status=405)

    # Parse JSON payload
    try:
        payload = request.get_json(force=True)
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
    except Exception as exc:
        logging.error(f"Invalid JSON body: {exc}")
        return _error_response(f"Invalid JSON body: {exc}", status=400)

    # Assemble package
    try:
        envelope = assemble_package(payload)
    except ValueError as exc:
        logging.error(f"Package assembly validation error: {exc}")
        return _error_response(str(exc), status=400)
    except Exception as exc:
        logging.exception("Failed to assemble package")
        return _error_response("Internal server error", status=500)

    return _cors_response(envelope.to_dict())


def _cors_response(body: dict[str, Any], status: int = 200) -> flask.Response:
    """Create a CORS-enabled response."""
    response = flask.make_response(json.dumps(body, ensure_ascii=False), status)
    response.headers["Content-Type"] = "application/json"
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "POST,OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


def _error_response(message: str, status: int) -> flask.Response:
    """Create an error response."""
    return _cors_response({"error": message}, status=status)
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
