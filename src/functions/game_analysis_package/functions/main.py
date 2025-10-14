"""
Cloud Function HTTP entry point for game analysis.

Exposes game analysis pipeline as an HTTP API endpoint.
Accepts POST requests with game package JSON and returns enriched analysis.
"""

import json
import logging
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent.absolute()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Setup environment and logging
from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging

load_env()
setup_logging()

logger = logging.getLogger(__name__)

# Import analysis components
from src.functions.game_analysis_package.core.contracts.game_package import (
    validate_game_package,
    ValidationError
)
from src.functions.game_analysis_package.core.extraction.player_extractor import (
    PlayerExtractor
)
from src.functions.game_analysis_package.core.bundling.request_builder import (
    DataRequestBuilder,
    RelevantPlayer
)


# CORS headers for browser access
CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Max-Age': '3600'
}


def analysis_handler(request):
    """
    HTTP Cloud Function entry point for game analysis.
    
    Handles:
    - OPTIONS: CORS preflight requests
    - POST: Game analysis requests
    
    Args:
        request: Flask request object
        
    Returns:
        Tuple of (response_data, status_code, headers)
    """
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        return ('', 204, CORS_HEADERS)
    
    # Only accept POST
    if request.method != 'POST':
        logger.warning(f"Method not allowed: {request.method}")
        return (
            {'error': 'Method not allowed. Use POST to submit game packages.'},
            405,
            CORS_HEADERS
        )
    
    try:
        # Parse request JSON
        try:
            request_data = request.get_json()
            if not request_data:
                return (
                    {'error': 'Invalid JSON or empty request body'},
                    400,
                    CORS_HEADERS
                )
        except Exception as e:
            logger.error(f"JSON parse error: {e}")
            return (
                {'error': f'Invalid JSON: {str(e)}'},
                400,
                CORS_HEADERS
            )
        
        # Log request
        game_id = (
            request_data.get('game_package', {}).get('game_id')
            or request_data.get('game_id', 'unknown')
        )
        logger.info(f"Processing game analysis request for {game_id}")
        
        # Validate game package
        try:
            package = validate_game_package(request_data)
        except ValidationError as e:
            logger.warning(f"Validation failed for {game_id}: {e}")
            return (
                {
                    'error': 'Validation failed',
                    'message': str(e),
                    'game_id': game_id
                },
                422,
                CORS_HEADERS
            )
        
        # Extract players
        extractor = PlayerExtractor()
        player_ids = extractor.extract_players(package.plays)
        logger.info(f"Extracted {len(player_ids)} players from {len(package.plays)} plays")
        
        # Build data request
        # For now, create mock relevant players from extracted IDs
        # In full implementation, this would come from relevance scoring
        relevant_players = [
            RelevantPlayer(player_id=pid, relevance_score=1.0)
            for pid in list(player_ids)[:20]  # Limit for initial implementation
        ]
        
        builder = DataRequestBuilder()
        request_obj = builder.build_request(
            game_info=package.get_game_info(),
            relevant_players=relevant_players
        )
        
        # Build response
        # In full implementation, this would include:
        # - Data fetching from upstream sources
        # - Normalization and merging
        # - Summarization
        # - Envelope creation
        
        response = {
            'schema_version': '1.0.0',
            'correlation_id': package.correlation_id or f"{package.game_id}-{os.urandom(4).hex()}",
            'status': 'success',
            'game_info': {
                'game_id': package.game_id,
                'season': package.season,
                'week': package.week,
            },
            'analysis_summary': {
                'plays_analyzed': len(package.plays),
                'players_extracted': len(player_ids),
                'relevant_players': len(relevant_players),
                'ngs_requests': len(request_obj.ngs_requests),
            },
            'enriched_package': {
                'note': 'Full implementation will include merged data from all sources',
                'data_request': request_obj.to_dict(),
            },
            'analysis_envelope': {
                'note': 'Full implementation will include LLM-ready compact envelope',
                'game_header': {
                    'game_id': package.game_id,
                    'season': package.season,
                    'week': package.week,
                },
            }
        }
        
        logger.info(f"Successfully processed game {package.game_id}")
        return (response, 200, CORS_HEADERS)
        
    except ValidationError as e:
        logger.error(f"Validation error: {e}")
        return (
            {
                'error': 'Validation failed',
                'message': str(e)
            },
            422,
            CORS_HEADERS
        )
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return (
            {
                'error': 'Internal server error',
                'message': 'An unexpected error occurred processing your request'
            },
            500,
            CORS_HEADERS
        )


# For local testing with Flask
if __name__ == '__main__':
    from flask import Flask, request
    
    app = Flask(__name__)
    
    @app.route('/', methods=['POST', 'OPTIONS'])
    def local_handler():
        """Local development handler."""
        response_data, status_code, headers = analysis_handler(request)
        return response_data, status_code, headers
    
    port = int(os.environ.get('PORT', 8080))
    print(f"Starting local server on http://localhost:{port}")
    app.run(host='0.0.0.0', port=port, debug=True)
