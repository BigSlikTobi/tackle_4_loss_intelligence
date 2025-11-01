#!/bin/bash
# Deployment script for game analysis Cloud Function
# Deploys the function to Google Cloud Functions

set -e

# Configuration
FUNCTION_NAME="game-analysis"
REGION="us-central1"
RUNTIME="python311"
ENTRY_POINT="analysis_handler"
MEMORY="512MB"
TIMEOUT="60s"

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

info "Deploying game analysis Cloud Function..."
echo ""
info "Configuration:"
echo "  Function: $FUNCTION_NAME"
echo "  Region: $REGION"
echo "  Runtime: $RUNTIME"
echo "  Memory: $MEMORY"
echo "  Timeout: $TIMEOUT"
echo ""

# Ensure we're in the functions directory
cd "$(dirname "$0")"

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    error "gcloud CLI not found. Please install it first."
    echo "See: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

# Check if user is authenticated
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>/dev/null | grep -q .; then
    error "Not authenticated with gcloud. Run 'gcloud auth login' first."
    exit 1
fi

# Get current project
PROJECT_ID=$(gcloud config get-value project 2>/dev/null)
if [ -z "$PROJECT_ID" ]; then
    error "No GCP project set. Run 'gcloud config set project PROJECT_ID' first."
    exit 1
fi

info "Deploying to project: $PROJECT_ID"
echo ""

info "Deployment will include the entire src/ tree for proper imports"

# Navigate to PROJECT ROOT (4 levels up: functions -> game_analysis_package -> functions -> src -> root)
cd ../../../..

info "Deploying from: $(pwd)"
info "This includes src/shared/ and src/functions/game_analysis_package/"

# Verify we're in the right place
if [ ! -d "src" ]; then
    error "src/ directory not found. Are we in the project root?"
    exit 1
fi

# Create temporary deployment directory
TEMP_DEPLOY_DIR=$(mktemp -d -t game-analysis-package-deploy.XXXXXX)
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
"""Deployment entry point for game_analysis_package Cloud Function."""

import json
import logging
from typing import Any
import flask

from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging

# Load environment and setup logging
load_env()
setup_logging()

logger = logging.getLogger(__name__)

# Import analysis components
from src.functions.game_analysis_package.core.contracts.game_package import (
    validate_game_package,
    ValidationError
)
from src.functions.game_analysis_package.core.pipeline import (
    GameAnalysisPipeline,
    PipelineConfig
)


def analysis_handler(request: flask.Request) -> flask.Response:
    """
    HTTP Cloud Function entry point for game analysis.
    
    Handles:
    - OPTIONS: CORS preflight requests
    - POST: Game analysis requests
    
    Args:
        request: Flask request object
        
    Returns:
        Flask Response with JSON data
    """
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        return _cors_response({}, status=204)
    
    # Only accept POST
    if request.method != 'POST':
        logger.warning(f"Method not allowed: {request.method}")
        return _error_response('Method not allowed. Use POST to submit game packages.', status=405)
    
    try:
        # Parse request JSON
        try:
            request_data = request.get_json(force=True)
            if not isinstance(request_data, dict):
                raise ValueError("JSON body must be an object")
        except Exception as e:
            logger.error(f"JSON parse error: {e}")
            return _error_response(f'Invalid JSON: {str(e)}', status=400)
        
        # Log request
        game_id = (
            request_data.get('game_package', {}).get('game_id')
            or request_data.get('game_id', 'unknown')
        )
        logger.info(f"Processing game analysis request for {game_id}")
        
        # Extract game_package from request
        game_package_data = request_data.get('game_package')
        if not game_package_data:
            logger.warning(f"Missing game_package field in request")
            return _error_response(
                'Request must include "game_package" field with game data',
                status=400
            )
        
        # Validate and create package
        try:
            package = validate_game_package(game_package_data)
        except ValidationError as e:
            logger.warning(f"Validation failed for {game_id}: {e}")
            return _error_response(str(e), status=422)
        
        # Check for fetch_data flag in request
        fetch_data = request_data.get('fetch_data', False)
        enable_envelope = request_data.get('enable_envelope', True)
        custom_correlation_id = request_data.get('correlation_id')
        
        # Configure pipeline
        config = PipelineConfig(
            fetch_data=fetch_data,
            strict_validation=False,  # Be lenient in production
            enable_envelope=enable_envelope,
            correlation_id=custom_correlation_id
        )
        
        # Execute pipeline
        pipeline = GameAnalysisPipeline()
        result = pipeline.process(package, config)
        
        # Check result status
        if result.status == 'failed':
            logger.error(f"Pipeline failed for {game_id}: {result.errors}")
            return _error_response(
                '; '.join(result.errors),
                status=500
            )
        
        # Build response
        response = {
            'schema_version': '1.0.0',
            'correlation_id': result.correlation_id,
            'status': result.status,
            'game_info': {
                'game_id': result.game_id,
                'season': result.season,
                'week': result.week,
            },
            'validation': {
                'passed': result.validation_passed,
                'warnings': result.validation_warnings,
            },
            'processing': {
                'players_extracted': result.players_extracted,
                'players_selected': result.players_selected,
                'data_fetched': result.data_fetched,
            },
        }
        
        # Add summaries if available
        if result.game_summaries:
            response['game_summaries'] = result.game_summaries.to_dict()
        
        # Add envelope if available
        if result.analysis_envelope:
            response['analysis_envelope'] = result.analysis_envelope.to_dict()
        
        # Add enriched package if available
        if result.merged_data:
            response['enriched_package'] = result.merged_data.to_dict()
        
        # Add warnings if present
        if result.warnings:
            response['warnings'] = result.warnings
        
        logger.info(
            f"Successfully processed game {package.game_id} "
            f"[{result.correlation_id}] - Status: {result.status}"
        )
        return _cors_response(response)
        
    except ValidationError as e:
        logger.error(f"Validation error: {e}")
        return _error_response(str(e), status=422)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return _error_response('An unexpected error occurred processing your request', status=500)


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

info "Entry point created"

# Create temporary requirements.txt that includes all dependencies
info "Creating requirements.txt..."
cat > "$TEMP_DEPLOY_DIR/requirements.txt" << 'EOF'
# Cloud Function Dependencies
functions-framework==3.*
flask==3.*

# Core dependencies
python-dotenv>=1.0.0

# Data processing
pandas>=2.0.0
numpy>=1.24.0

# Database
supabase>=2.0.0

# Type checking
typing-extensions>=4.5.0

# Data loading dependencies (required for dynamic play fetching)
nflreadpy>=0.1.0
nfl-data-py>=0.3.0
pytz>=2023.3
pyarrow>=10.0.0
requests>=2.31.0
beautifulsoup4>=4.12.0
EOF

info "Requirements file created"
echo ""

# Deploy the function from temporary directory
info "Deploying function from temporary directory..."
gcloud functions deploy $FUNCTION_NAME \
    --gen2 \
    --region=$REGION \
    --runtime=$RUNTIME \
    --entry-point=$ENTRY_POINT \
    --trigger-http \
    --allow-unauthenticated \
    --memory=$MEMORY \
    --timeout=$TIMEOUT \
    --source="$TEMP_DEPLOY_DIR" \
    --clear-env-vars \
    --clear-secrets

# Cleanup handled by trap

echo ""
info "✓ Deployment complete!"
echo ""
echo "Function URL:"
gcloud functions describe $FUNCTION_NAME --region=$REGION --gen2 --format="value(serviceConfig.uri)"
echo ""
echo "Test with:"
echo "curl -X POST \$(gcloud functions describe $FUNCTION_NAME --region=$REGION --gen2 --format='value(serviceConfig.uri)') \\"
echo "  -H 'Content-Type: application/json' \\"
echo "  -d @src/functions/game_analysis_package/test_requests/http_api_test_minimal.json"

