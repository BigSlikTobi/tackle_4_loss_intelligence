import asyncio
import functions_framework
from flask import Request, Response
from ..core.factory import TTSFactory
from ..core.service import TTSService

@functions_framework.http
def generate_speech_http(request: Request) -> Response:
    """HTTP Cloud Function entry point."""
    
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
        'Access-Control-Allow-Origin': '*'
    }

    try:
        # Parse Request
        request_json = request.get_json(silent=True)
        if not request_json:
            return Response("Invalid JSON payload", 400, headers)
            
        tts_request = TTSFactory.create_request(request_json)
        
        # specific to async implementation in sync flask handler
        tts_response = asyncio.run(TTSService.generate_speech(tts_request))
        
        # Return Audio File
        return Response(
            tts_response.audio_content,
            mimetype="audio/mpeg",
            headers=headers
        )

    except ValueError as e:
        return Response(str(e), 400, headers)
    except RuntimeError as e:
        return Response(str(e), 502, headers)
    except Exception as e:
        return Response(f"Internal Server Error: {str(e)}", 500, headers)
