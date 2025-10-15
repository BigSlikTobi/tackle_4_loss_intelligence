"""
Cloud Function HTTP entry point for game analysis.

Exposes game analysis pipeline as an HTTP API endpoint.
Accepts POST requests with game package JSON and returns enriched analysis.
"""

import json
import logging
import sys
from pathlib import Path
from typing import Any

import flask

# Add project root to path FIRST
# From functions/main.py: go up to functions -> game_analysis_package -> functions -> src -> project_root (5 levels)
project_root = Path(__file__).parent.parent.parent.parent.parent.absolute()
sys.path.insert(0, str(project_root))

# Now import after path is set
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
        
        # Check if plays will be fetched dynamically
        game_package_temp = request_data.get('game_package', {})
        plays_provided = game_package_temp.get('plays', [])
        will_fetch_plays = not plays_provided or len(plays_provided) == 0
        
        if will_fetch_plays:
            logger.info(f"Processing game analysis request for {game_id} (will fetch plays from database)")
        else:
            logger.info(f"Processing game analysis request for {game_id} (using {len(plays_provided)} provided plays)")
        
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
                'plays_fetched_dynamically': will_fetch_plays,  # NEW: Indicate if plays were auto-fetched
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
