# Image Selection Module

This module provides HTTP endpoints that curate article images from common-usage sources,
store them in Supabase storage, and persist metadata in the `article_images` table.

## Features
- Google Custom Search (with Creative Commons filters) as the primary provider.
- DuckDuckGo Images fallback when Google returns no eligible results.
- Automatic DuckDuckGo fallback when Google Custom Search credentials are not supplied.
- Optional LLM-assisted query optimization (Gemini or GPT models).
- Strict domain blacklist to avoid stock imagery and thumbnails.
- Optional Supabase storage upload and metadata insertion (supply credentials per request).

> **Security note:** the Cloud Function does not rely on environment-stored secrets. Callers include
> their own API keys (LLM, Google Custom Search, Supabase) inside each request payload, so anyone can
> use the deployed function without exposing shared credentials.

## HTTP API
The Cloud Function entry point is defined in `functions/main.py` and exposes two routes:

- `POST /select_article_images` – runs the image search workflow.
- `GET /health_check` – basic health probe.

## CLI Tool
Use `scripts/select_images_cli.py` for local experimentation without deploying the Cloud Function:

```
cd src/functions/image_selection
python scripts/select_images_cli.py \ 
  --article-file path/to/article.txt \ 
  --num-images 2 \ 
  --llm-provider gemini \ 
  --llm-model gemini-2.0-flash \ 
  --llm-api-key $GEMINI_API_KEY \ 
  --search-api-key $GOOGLE_CUSTOM_SEARCH_KEY \ 
  --search-engine-id $GOOGLE_CUSTOM_SEARCH_ENGINE_ID \ 
  --supabase-url $SUPABASE_URL \ 
  --supabase-key $SUPABASE_SERVICE_ROLE_KEY
```

Provide `--config payload.json` to reuse the HTTP payload format, and `--output result.json`
to write the response to disk.

If you omit `--search-api-key` / `--search-engine-id`, the CLI will skip Google Custom Search and
fall back to DuckDuckGo-only image discovery.

If you omit `--supabase-url` / `--supabase-key`, the CLI will still return image results but will
not upload them to Supabase. This mirrors the Cloud Function behaviour when the `supabase` block is
omitted from the payload.

### Request Payload
```jsonc
{
  "article_text": "Full article body…",          // optional when `query` provided
  "query": "fallback keywords",                 // optional when `article_text` provided
  "num_images": 2,                                // required >= 1
  "enable_llm": true,                             // defaults to true
  "llm": {
    "provider": "gemini",                        // "gemini" | "openai"
    "model": "gemini-2.0-flash",                 // required when `enable_llm`
    "api_key": "...",                            // required when `enable_llm`
    "parameters": {"temperature": 0.4},          // provider specific options
    "prompt_template": null,                      // optional custom prompt
    "max_query_words": 8                          // optional cap on query length
  },
  "search": {
    "api_key": "...",                            // Google Custom Search API key
    "engine_id": "...",                          // Programmable Search Engine ID
    "rights": "cc_publicdomain,cc_attribute,cc_sharealike", // optional overrides
    "image_type": "photo",                       // optional
    "image_size": "large"                        // optional
  },                                               // omit entire block to skip Google search
  // omit or set {"enabled": false} when you do not want to upload images
  "supabase": {
    "url": "https://<project>.supabase.co",
    "key": "...",                                // service role recommended
    "bucket": "images",                          // optional (defaults to images)
    "table": "article_images"                    // optional (defaults to article_images)
  }
}
```

### Successful Response
```json
{
  "status": "success",
  "count": 2,
  "query": "san francisco 49ers touchdown",
  "images": [
    {
      "image_url": "https://.../storage/v1/object/public/images/public/hash_123.jpg",
      "original_url": "https://source-site/image.jpg",
      "author": "Jane Smith",
      "source": "commons.wikimedia.org",
      "width": 1600,
      "height": 900,
      "title": "Monday Night Football celebration"
    }
  ]
}
```

  When Supabase is disabled the `image_url` will match `original_url`, allowing the caller to decide
  how to host or cache the asset.

## Deployment
```
cd functions
pip install -r requirements.txt
functions-framework --target select_article_images
```

For Cloud Functions deployment, use the standard module pattern described in
`docs/architecture/function_isolation.md`. The provided `functions/deploy.sh` script does **not**
configure Secret Manager entries; instead, each caller supplies their own credentials within the
request payload.

## Testing
- Provide valid Google Custom Search and Supabase credentials in the request payload.
- The service enforces domain blacklists and Creative Commons licenses; expect some
  inputs to yield zero results if no compliant images are found.
