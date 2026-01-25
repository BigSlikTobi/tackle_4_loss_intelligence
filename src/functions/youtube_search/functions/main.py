import asyncio
import json
import functions_framework
from flask import Request, Response
from ..core.factory import YouTubeSearchFactory
from ..core.service import YouTubeSearchService


@functions_framework.http
def youtube_search_http(request: Request) -> Response:
    """HTTP Cloud Function entry point for YouTube Search."""
    
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'POST',
            'Access-Control-Allow-Headers': 'Content-Type',
            'Access-Control-Max-Age': '3600'
        }
        return Response('', 204, headers)

    # Set CORS headers for the main request
    headers = {
        'Access-Control-Allow-Origin': '*',
        'Content-Type': 'application/json'
    }

    try:
        # Parse Request
        request_json = request.get_json(silent=True)
        if not request_json:
            return Response(
                json.dumps({"error": "Invalid JSON payload"}),
                400,
                headers
            )
            
        search_request = YouTubeSearchFactory.create_request(request_json)
        
        # Execute async search
        search_response = asyncio.run(YouTubeSearchService.search(search_request))
        
        # Return JSON response
        return Response(
            search_response.model_dump_json(),
            200,
            headers
        )

    except ValueError as e:
        return Response(
            json.dumps({"error": str(e)}),
            400,
            headers
        )
    except RuntimeError as e:
        return Response(
            json.dumps({"error": str(e)}),
            502,
            headers
        )
    except Exception as e:
        return Response(
            json.dumps({"error": f"Internal Server Error: {str(e)}"}),
            500,
            headers
        )
