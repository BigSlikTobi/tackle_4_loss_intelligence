# Gemini TTS Batch Function

Asynchronous batch Text-to-Speech service built on the Gemini Batch API.

This module is separate from `src/functions/gemini_tts/` on purpose:
- `gemini_tts` stays a single-request, binary-MP3 endpoint.
- `gemini_tts_batch` manages batch job lifecycle with JSON responses.

## Actions

The HTTP function accepts a JSON body with an `action` field.

### `action=create`

Creates a Gemini batch job from multiple article-like inputs.

**Option A — plain text** (simplest):

```json
{
  "action": "create",
  "model_name": "gemini-2.5-pro-preview-tts",
  "voice_name": "Charon",
  "items": [
    {
      "id": "story-1",
      "text": "The 49ers advanced to the playoffs after a stunning victory.",
      "title": "49ers Clinch Playoff Spot"
    },
    {
      "id": "story-2",
      "text": "Patrick Mahomes returned to practice on Monday.",
      "voice_name": "Kore"
    }
  ],
  "credentials": {
    "gemini": "YOUR_GEMINI_API_KEY"
  }
}
```

**Option B — pre-rendered `tts_prompt`** (full control over the prompt string):

```json
{
  "action": "create",
  "model_name": "gemini-2.5-pro-preview-tts",
  "items": [
    {
      "id": "story-1",
      "tts_prompt": "<speak>Speak this exactly as written.</speak>"
    }
  ],
  "credentials": {"gemini": "YOUR_GEMINI_API_KEY"}
}
```

**Option C — structured `direction` + `script`** (preferred for long-form news/sports content):

```json
{
  "action": "create",
  "model_name": "gemini-2.5-pro-preview-tts",
  "items": [
    {
      "id": "story-1",
      "title": "AFC East shockwave",
      "direction": {
        "audio_profile": "Single-anchor, live-breaking NFL news hit with a tight, driving rhythm",
        "scene": "Top of the hour on a national NFL network",
        "audience": "NFL fans on mobile",
        "director_notes": "Open hot in the first 15 seconds, then ease slightly for cap numbers",
        "pace": "Urgent but controlled — no rambling",
        "warmth": "Cool and commanding",
        "must_hit": [
          "record 99 million in dead money",
          "three years, 40 million"
        ],
        "pronunciations": [
          {"term": "Tagovailoa", "guide": "TAH-go-vai-LOH-uh"}
        ]
      },
      "script": {
        "intro": "Mason Reed with you...",
        "body": "Let's start with the headline move...",
        "outro": "Keep your eye on two things now..."
      }
    }
  ],
  "credentials": {
    "gemini": "YOUR_GEMINI_API_KEY"
  }
}
```

You can also combine `direction` with a plain `text` field (no `script`) when the body copy is already a single block:

```json
{
  "id": "story-1",
  "title": "Breaking News",
  "direction": {"audio_profile": "Live news hit", "pace": "Fast"},
  "text": "Full article body goes here as one string."
}
```

**`direction` field reference:**

| Field | Description |
|---|---|
| `audio_profile` | Big-picture voice and style description |
| `scene` | Where/when the anchor is delivering |
| `audience` | Who is listening |
| `director_notes` | Micro-cues (pacing shifts, emphasis points) |
| `pace` | Overall speed guidance |
| `warmth` | Emotional tone or energy level |
| `must_hit` | List of phrases that must be clearly emphasised |
| `pronunciations` | List of `{"term": "…", "guide": "…"}` objects — **must be objects, not strings** |

For local use, `credentials.gemini` can be omitted if `GEMINI_API_KEY` is available in the environment or the repo `.env`. Explicit request credentials still take precedence.

### `action=status`

```json
{
  "action": "status",
  "batch_id": "batches/abc123",
  "credentials": {
    "gemini": "YOUR_GEMINI_API_KEY"
  }
}
```

### `action=process`

Downloads a completed batch output, converts each item to MP3 when needed, uploads it to Supabase Storage, and writes a manifest.

```json
{
  "action": "process",
  "batch_id": "batches/abc123",
  "supabase": {
    "url": "https://PROJECT.supabase.co",
    "key": "YOUR_SUPABASE_KEY",
    "bucket": "audio",
    "path_prefix": "gemini-tts-batch"
  }
}
```

## Model Compatibility

Batch creation validates model support by querying Gemini model metadata at runtime. A model must advertise `batchGenerateContent`.

In this repository's current environment, `gemini-2.5-pro-preview-tts` is batch-capable while `gemini-2.5-flash-preview-tts` is not.

## Partial Failures and Token Usage

`process` handles per-item failures gracefully. Items that Gemini could not synthesise are recorded in the `failures` list of the response and in the uploaded `manifest.json` — they do **not** abort the whole batch.

Each `process` response includes aggregated token counts:

```json
{
  "token_usage": {
    "input_tokens": 4200,
    "cached_input_tokens": 300,
    "output_tokens": 1100,
    "total_tokens": 5300,
    "reported_item_count": 10
  }
}
```

`reported_item_count` is the number of items whose usage metadata was present in the output file (some items may not report usage if they errored before generation). Per-item token usage is also included in each entry under `items[*].token_usage`.

A `usage_summary.json` file is uploaded alongside the manifest and a local copy is written to the service working directory for offline inspection.

## Local Development

```bash
cd src/functions/gemini_tts_batch
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

Run locally:

```bash
cd functions
./run_local.sh
```

CLI test helper:

```bash
python scripts/tts_batch_cli.py --payload-file request.json
```

## Deployment

```bash
cd functions
./deploy.sh
```

For local development, the service can read `GEMINI_API_KEY` from the central `.env`. For deployed usage, passing `credentials.gemini` in the request remains the safest option unless you explicitly configure the function environment.
