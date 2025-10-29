#!/bin/bash
# Deployment script for the article translation Cloud Function

set -euo pipefail

FUNCTION_NAME="article-translation"
REGION="us-central1"
RUNTIME="python312"
ENTRY_POINT="article_translation_handler"
MEMORY="2048MB"
TIMEOUT="540s"

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

info "Generating deployment entry point wrapper"
cat > main.py <<'EOF'
"""Deployment wrapper for the article translation Cloud Function."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict

import flask

project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.functions.article_translation.functions.main import handle_request

logger = logging.getLogger(__name__)


def article_translation_handler(request: flask.Request) -> flask.Response:
    if request.method == "OPTIONS":
        return _cors_response({}, status=204)

    if request.method != "POST":
        return _cors_response({"status": "error", "message": "Method not allowed. Use POST."}, status=405)

    try:
        payload: Dict[str, Any] = request.get_json(silent=True) or {}
        result = handle_request(payload)
        status_code = 200 if result.get("status") == "success" else 400
        return _cors_response(result, status=status_code)
    except Exception as exc:
        logger.exception("Unexpected error in article translation handler")
        return _cors_response(
            {"status": "error", "message": f"Internal error: {exc}"},
            status=500
        )


def _cors_response(body: Dict[str, Any] | list[Any], status: int = 200) -> flask.Response:
    response = flask.make_response(json.dumps(body, ensure_ascii=False), status)
    headers = response.headers
    headers["Content-Type"] = "application/json; charset=utf-8"
    headers["Access-Control-Allow-Origin"] = "*"
    headers["Access-Control-Allow-Methods"] = "POST,OPTIONS"
    headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    return response
EOF

info "Creating requirements.txt"
cat > requirements.txt <<'EOF'
functions-framework==3.*
flask==3.*
python-dotenv>=1.0.0
openai>=1.51.0
pydantic>=2.9.0
tenacity>=8.3.0
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
  --timeout="${TIMEOUT}" \
  --source=. \
  --set-env-vars="LOG_LEVEL=INFO" \
  --clear-secrets

info "Cleaning up temporary files"
rm -f main.py requirements.txt

info "Deployment complete"

FUNCTION_URL=$(gcloud functions describe "${FUNCTION_NAME}" --region="${REGION}" --gen2 --format="value(serviceConfig.uri)")
if [ -n "$FUNCTION_URL" ]; then
  echo ""
  info "Function URL: ${FUNCTION_URL}"
  echo "Test with:"
  echo "curl -X POST ${FUNCTION_URL} \\
    -H 'Content-Type: application/json' \\
    -d '{"article": {}}'"
else
  warn "Unable to fetch function URL automatically."
fi
