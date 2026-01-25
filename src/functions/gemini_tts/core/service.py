import base64
import io
import httpx
from pydub import AudioSegment
from .config import TTSRequest, TTSResponse

class TTSService:
    @staticmethod
    async def generate_speech(request: TTSRequest) -> TTSResponse:
        """Generates speech using Gemini API and converts to MP3."""
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{request.model_name}:generateContent?key={request.credentials.gemini}"
        
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": request.text}
                    ]
                }
            ],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "temperature": 1,
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {
                            "voiceName": request.voice_name
                        }
                    }
                }
            }
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=60.0)
            
            if response.status_code != 200:
                error_msg = response.text
                try:
                    error_json = response.json()
                    if "error" in error_json:
                        error_msg = error_json["error"].get("message", error_msg)
                except:
                    pass
                raise RuntimeError(f"Gemini API Error ({response.status_code}): {error_msg}")
                
            data = response.json()
            
            # Parsing response logic:
            # The structure for AUDIO response is usually in `candidates[0].content.parts[0].inlineData`
            try:
                if not data.get("candidates"):
                     raise ValueError("Gemini returned no candidates.")

                candidate = data["candidates"][0]
                
                # Check for safety finish reason
                finish_reason = candidate.get("finishReason")
                if finish_reason and finish_reason != "STOP":
                    raise ValueError(f"Gemini processing stopped due to: {finish_reason}")
                
                if "content" not in candidate:
                     raise ValueError(f"Gemini response candidate missing content. Finish reason: {finish_reason}")

                part = candidate["content"]["parts"][0]
                
                if "inlineData" not in part:
                    raise ValueError("No audio data found in response inlineData")
                
                inline_data = part["inlineData"]
                audio_b64 = inline_data["data"]
                mime_type = inline_data.get("mimeType", "audio/wav")
                
                audio_bytes = base64.b64decode(audio_b64)
                
                # Determine format from mimeType
                # Common formats: audio/wav, audio/L16, audio/pcm, audio/mpeg
                if "L16" in mime_type or "pcm" in mime_type.lower():
                    # Raw PCM audio - need to wrap in proper container
                    # Gemini typically uses 24kHz, 16-bit, mono for TTS
                    # Parse sample rate from mime type if present (e.g., audio/L16;rate=24000)
                    sample_rate = 24000
                    sample_width = 2  # 16-bit = 2 bytes
                    channels = 1
                    
                    if "rate=" in mime_type:
                        try:
                            rate_str = mime_type.split("rate=")[1].split(";")[0].split(",")[0]
                            sample_rate = int(rate_str)
                        except:
                            pass
                    
                    audio = AudioSegment(
                        data=audio_bytes,
                        sample_width=sample_width,
                        frame_rate=sample_rate,
                        channels=channels
                    )
                elif "wav" in mime_type.lower():
                    audio = AudioSegment.from_file(io.BytesIO(audio_bytes), format="wav")
                elif "mpeg" in mime_type.lower() or "mp3" in mime_type.lower():
                    # Already MP3 - just return it
                    return TTSResponse(audio_content=audio_bytes)
                else:
                    # Try auto-detection
                    audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
                
                # Convert to MP3
                mp3_buffer = io.BytesIO()
                audio.export(mp3_buffer, format="mp3", bitrate="192k")
                mp3_bytes = mp3_buffer.getvalue()
                
                return TTSResponse(audio_content=mp3_bytes)
                
            except (KeyError, IndexError) as e:
                raise RuntimeError(f"Unexpected response format from Gemini: {str(e)}")
