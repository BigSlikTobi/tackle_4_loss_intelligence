# Gemini TTS Function

Type-safe, production-ready Text-to-Speech service using Google's Gemini 2.5 Flash Audio model.

## Features

- **Gemini 2.5 Flash Audio**: High-quality, low-latency speech synthesis.
- **Async Processing**: Built on `asyncio` for non-blocking I/O.
- **Factory Pattern**: Type-safe request parsing and validation.
- **CORS Support**: Ready for web frontend integration.

## API Usage

### Request Format

```json
{
  "text": "The 49ers advanced to the playoffs after a stunning victory.",
  "model_name": "gemini-2.5-flash-preview-tts",
  "voice_name": "Charon",
  "credentials": {
    "gemini": "YOUR_GEMINI_API_KEY"
  }
}
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `text` | string | Yes | The text content to convert to speech. |
| `model_name` | string | Yes | Target Gemini model (e.g. `gemini-2.5-flash-preview-tts`). |
| `voice_name` | string | No | Voice profile (default: `Charon`). |
| `credentials.gemini` | string | Yes | Google AI Studio API key. |

### Response

Returns raw **MP3 audio data** with `Content-Type: audio/mpeg`.

## Local Development

### Setup

```bash
cd src/functions/gemini_tts
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### Run Locally

```bash
cd functions
./run_local.sh
```

### Test

```bash
curl -X POST http://localhost:8080 \
  -H "Content-Type: application/json" \
  --output output.mp3 \
  -d '{
    "text": "Hello world from Gemini TTS", 
    "model_name": "gemini-2.5-flash-preview-tts",
    "credentials": {"gemini": "YOUR_KEY"}
  }'
```

## Deployment

Deploy as a standard Google Cloud Function:

```bash
cd functions
./deploy.sh
```
