from typing import Optional
from pydantic import BaseModel, Field

class Credentials(BaseModel):
    gemini: str = Field(..., description="Gemini API Key")

class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Text to convert to speech")
    model_name: str = Field(..., description="Gemini model name, e.g., gemini-2.5-flash-preview-tts")
    voice_name: str = Field("Charon", description="Voice name to use")
    credentials: Credentials = Field(..., description="API Credentials")

class TTSResponse(BaseModel):
    audio_content: bytes = Field(..., description="Raw MP3 audio bytes")
