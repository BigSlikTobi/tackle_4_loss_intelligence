from typing import Any, Dict
from .config import YouTubeSearchRequest


class YouTubeSearchFactory:
    """Factory for parsing and validating YouTube Search requests."""
    
    @staticmethod
    def create_request(json_data: Dict[str, Any]) -> YouTubeSearchRequest:
        """Parses and validates the incoming JSON request.
        
        Args:
            json_data: Raw JSON payload from HTTP request.
            
        Returns:
            Validated YouTubeSearchRequest object.
            
        Raises:
            ValueError: If request format is invalid.
        """
        try:
            return YouTubeSearchRequest(**json_data)
        except Exception as e:
            raise ValueError(f"Invalid request format: {str(e)}")
