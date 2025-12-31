#!/bin/bash
# Deployment script for the URL content extraction Cloud Function

set -euo pipefail

FUNCTION_NAME="url-content-extraction"
REGION="us-central1"
RUNTIME="python312"
ENTRY_POINT="url_content_extraction_handler"
MEMORY="2048MB"  # Increased for Playwright - gives ~1.2 CPU cores
TIMEOUT="540s"
CPU="2"  # Explicitly allocate 2 CPU cores for faster extraction

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"

info "Preparing deployment for ${FUNCTION_NAME}"

if [ ! -d "${PROJECT_ROOT}/src" ]; then
  error "Unable to locate project root. Expected src/ directory at ${PROJECT_ROOT}."
  exit 1
fi

if ! command -v gcloud >/dev/null 2>&1; then
  error "gcloud CLI not found. Install the Cloud SDK first."
  exit 1
fi

ACTIVE_ACCOUNT=$(gcloud auth list --filter=status:ACTIVE --format="value(account)")
if [ -z "$ACTIVE_ACCOUNT" ]; then
  error "No active gcloud account. Run 'gcloud auth login' first."
  exit 1
fi

PROJECT_ID=$(gcloud config get-value project 2>/dev/null)
if [ -z "$PROJECT_ID" ]; then
  error "No GCP project configured. Run 'gcloud config set project PROJECT_ID'."
  exit 1
fi

info "Deploying to project: ${PROJECT_ID} (account: ${ACTIVE_ACCOUNT})"

cd "$PROJECT_ROOT"

DEFAULT_PLAYWRIGHT_SUBPATH=".playwright"
REQUESTED_PLAYWRIGHT_PATH="${PLAYWRIGHT_BROWSERS_PATH:-}"

if [[ -z "${REQUESTED_PLAYWRIGHT_PATH}" ]]; then
  RUNTIME_PLAYWRIGHT_PATH="/workspace/${DEFAULT_PLAYWRIGHT_SUBPATH}"
  PLAYWRIGHT_SUBPATH="${DEFAULT_PLAYWRIGHT_SUBPATH}"
elif [[ "${REQUESTED_PLAYWRIGHT_PATH}" == /workspace/* ]]; then
  RUNTIME_PLAYWRIGHT_PATH="${REQUESTED_PLAYWRIGHT_PATH%/}"
  PLAYWRIGHT_SUBPATH="${RUNTIME_PLAYWRIGHT_PATH#/workspace/}"
elif [[ "${REQUESTED_PLAYWRIGHT_PATH}" == /* ]]; then
  warn "PLAYWRIGHT_BROWSERS_PATH=${REQUESTED_PLAYWRIGHT_PATH} is outside /workspace; defaulting to /workspace/${DEFAULT_PLAYWRIGHT_SUBPATH}"
  RUNTIME_PLAYWRIGHT_PATH="/workspace/${DEFAULT_PLAYWRIGHT_SUBPATH}"
  PLAYWRIGHT_SUBPATH="${DEFAULT_PLAYWRIGHT_SUBPATH}"
else
  CLEAN_RELATIVE="${REQUESTED_PLAYWRIGHT_PATH#/}"
  if [[ -z "${CLEAN_RELATIVE}" ]]; then
    CLEAN_RELATIVE="${DEFAULT_PLAYWRIGHT_SUBPATH}"
  fi
  PLAYWRIGHT_SUBPATH="${CLEAN_RELATIVE%/}"
  RUNTIME_PLAYWRIGHT_PATH="/workspace/${PLAYWRIGHT_SUBPATH}"
fi

if [[ -z "${PLAYWRIGHT_SUBPATH}" ]]; then
  PLAYWRIGHT_SUBPATH="${DEFAULT_PLAYWRIGHT_SUBPATH}"
  RUNTIME_PLAYWRIGHT_PATH="/workspace/${PLAYWRIGHT_SUBPATH}"
fi

if [[ "${PLAYWRIGHT_SUBPATH}" == *".."* ]]; then
  warn "PLAYWRIGHT_BROWSERS_PATH may not traverse directories; defaulting to /workspace/${DEFAULT_PLAYWRIGHT_SUBPATH}"
  PLAYWRIGHT_SUBPATH="${DEFAULT_PLAYWRIGHT_SUBPATH}"
  RUNTIME_PLAYWRIGHT_PATH="/workspace/${PLAYWRIGHT_SUBPATH}"
fi

if [[ "${PLAYWRIGHT_SUBPATH}" == *" "* ]]; then
  warn "PLAYWRIGHT_BROWSERS_PATH cannot contain spaces; defaulting to /workspace/${DEFAULT_PLAYWRIGHT_SUBPATH}"
  PLAYWRIGHT_SUBPATH="${DEFAULT_PLAYWRIGHT_SUBPATH}"
  RUNTIME_PLAYWRIGHT_PATH="/workspace/${PLAYWRIGHT_SUBPATH}"
fi

LOCAL_PLAYWRIGHT_DIR="${PROJECT_ROOT}/${PLAYWRIGHT_SUBPATH}"

info "Preparing Playwright browser bundle at ${LOCAL_PLAYWRIGHT_DIR} (runtime: ${RUNTIME_PLAYWRIGHT_PATH})"
rm -rf "${LOCAL_PLAYWRIGHT_DIR}"
mkdir -p "${LOCAL_PLAYWRIGHT_DIR}"

if command -v docker >/dev/null 2>&1; then
  info "Downloading Linux Chromium bundle via Playwright Docker image"
  docker run --rm --platform linux/amd64 \
    -v "${PROJECT_ROOT}":/workspace \
    -w /workspace \
    mcr.microsoft.com/playwright/python:v1.48.0 \
    bash -c "pip install --no-cache-dir 'playwright>=1.48,<1.49' >/dev/null 2>&1 && PLAYWRIGHT_BROWSERS_PATH=/workspace/${PLAYWRIGHT_SUBPATH} python -m playwright install --with-deps chromium"
  
  info "Creating chromium_headless_shell symlink for Playwright compatibility"
  cd "${LOCAL_PLAYWRIGHT_DIR}"
  for chromium_dir in chromium-*/ ; do
    if [ -d "$chromium_dir" ]; then
      revision="${chromium_dir#chromium-}"
      revision="${revision%/}"
      shell_dir="chromium_headless_shell-${revision}"
      if [ ! -e "$shell_dir" ]; then
        ln -s "chromium-${revision}" "$shell_dir"
        info "Created symlink: $shell_dir -> chromium-${revision}"
      fi
    fi
  done
  cd "$PROJECT_ROOT"
else
  warn "Docker not available; installing local Playwright browsers (may not match Linux runtime)"
  PLAYWRIGHT_BROWSERS_PATH="${LOCAL_PLAYWRIGHT_DIR}" python3 -m playwright install --with-deps chromium
  
  info "Creating chromium_headless_shell symlink for Playwright compatibility"
  cd "${LOCAL_PLAYWRIGHT_DIR}"
  for chromium_dir in chromium-*/ ; do
    if [ -d "$chromium_dir" ]; then
      revision="${chromium_dir#chromium-}"
      revision="${revision%/}"
      shell_dir="chromium_headless_shell-${revision}"
      if [ ! -e "$shell_dir" ]; then
        ln -s "chromium-${revision}" "$shell_dir"
        info "Created symlink: $shell_dir -> chromium-${revision}"
      fi
    fi
  done
  cd "$PROJECT_ROOT"
fi

# Create temporary deployment directory
TEMP_DEPLOY_DIR=$(mktemp -d -t url-content-extraction-deploy.XXXXXX)
info "Created temporary deployment directory: $TEMP_DEPLOY_DIR"

# Set up cleanup trap
cleanup() {
  if [ -n "$TEMP_DEPLOY_DIR" ] && [ -d "$TEMP_DEPLOY_DIR" ]; then
    info "Cleaning up temporary directory: $TEMP_DEPLOY_DIR"
    rm -rf "$TEMP_DEPLOY_DIR"
  fi
}
trap cleanup EXIT

# Copy source code to temporary directory
info "Copying source code to temporary directory"
cp -r src "$TEMP_DEPLOY_DIR/"

# Copy Playwright browsers to deployment directory
info "Copying Playwright browsers to deployment directory"
mkdir -p "${TEMP_DEPLOY_DIR}/${PLAYWRIGHT_SUBPATH}"
cp -r "${LOCAL_PLAYWRIGHT_DIR}"/* "${TEMP_DEPLOY_DIR}/${PLAYWRIGHT_SUBPATH}/"

info "Generating deployment entry point wrapper"
cat > "$TEMP_DEPLOY_DIR/main.py" <<'EOF'
"""Deployment wrapper for the URL content extraction Cloud Function."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

import flask

project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.functions.url_content_extraction.functions.main import handle_request


def url_content_extraction_handler(request: flask.Request) -> flask.Response:
    if request.method == "OPTIONS":
        return _cors_response({}, status=204)

    payload: Dict[str, Any] = request.get_json(silent=True) or {}
    result = handle_request(payload)
    return _cors_response(result)


def _cors_response(body: Dict[str, Any] | list[Any], status: int = 200) -> flask.Response:
    response = flask.make_response(json.dumps(body, ensure_ascii=False), status)
    headers = response.headers
    headers["Content-Type"] = "application/json"
    headers["Access-Control-Allow-Origin"] = "*"
    headers["Access-Control-Allow-Methods"] = "POST,OPTIONS"
    headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    return response
EOF

info "Creating requirements.txt"
cat > "$TEMP_DEPLOY_DIR/requirements.txt" <<'EOF'
functions-framework==3.*
flask==3.*
python-dotenv>=1.0.0
beautifulsoup4>=4.12
httpx[http2]>=0.27
lxml>=5.1
playwright>=1.48,<1.49
pydantic>=2.9
supabase>=2.10
requests>=2.32
postgrest>=0.10
EOF

info "Deploying Cloud Function"
gcloud functions deploy "${FUNCTION_NAME}" \
  --gen2 \
  --region="${REGION}" \
  --runtime="${RUNTIME}" \
  --entry-point="${ENTRY_POINT}" \
  --trigger-http \
  --allow-unauthenticated \
  --memory="${MEMORY}" \
  --cpu="${CPU}" \
  --timeout="${TIMEOUT}" \
  --source="$TEMP_DEPLOY_DIR" \
  --set-env-vars="LOG_LEVEL=INFO,PLAYWRIGHT_BROWSERS_PATH=${RUNTIME_PLAYWRIGHT_PATH}" \
  --clear-secrets

# Cleanup handled by trap

info "Deployment complete"

FUNCTION_URL=$(gcloud functions describe "${FUNCTION_NAME}" --region="${REGION}" --gen2 --format="value(serviceConfig.uri)")
if [ -n "$FUNCTION_URL" ]; then
  echo ""
  info "Function URL: ${FUNCTION_URL}"
  echo "Test with:"
  echo "curl -X POST ${FUNCTION_URL} \\
    -H 'Content-Type: application/json' \\
    -d '{"urls": []}'"
else
  warn "Unable to fetch function URL automatically."
fi
