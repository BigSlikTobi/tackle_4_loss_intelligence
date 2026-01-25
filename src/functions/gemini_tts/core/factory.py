from typing import Any, Dict
from .config import TTSRequest

class TTSFactory:
    @staticmethod
    def create_request(json_data: Dict[str, Any]) -> TTSRequest:
        """Parses and validates the incoming JSON request."""
        try:
            return TTSRequest(**json_data)
        except Exception as e:
            raise ValueError(f"Invalid request format: {str(e)}")
