# Game News URLs Edge Function

This Supabase Edge Function returns all news URLs associated with a specific game.

## Deployment

```bash
cd functions
supabase functions deploy game-news-urls
```

## Invocation

```bash
supabase functions invoke game-news-urls --query "game_id=1234"
```

### Query Parameters

- `game_id` *(required)*: Game identifier used to resolve story groups.
- `max_urls` *(optional)*: Maximum URLs to return. Defaults to `GAME_NEWS_MAX_URLS` env value (200).
- `timeout_ms` *(optional)*: Request timeout in milliseconds. Defaults to `GAME_NEWS_TIMEOUT_MS` env value (10000).
- `concurrency` *(optional)*: Parallel fetch workers when loading URLs. Defaults to `GAME_NEWS_CONCURRENCY` env value (4).

## Response

```json
{
  "game_id": "1234",
  "count": 3,
  "urls": [
    "https://example.com/news/story-one",
    "https://example.com/news/story-two",
    "https://example.com/news/story-three"
  ],
  "url_items": [
    { "url": "https://example.com/news/story-one" },
    { "url": "https://example.com/news/story-two" },
    { "url": "https://example.com/news/story-three" }
  ]
}
```

The function normalizes and deduplicates URLs by trimming whitespace, lowercasing scheme and host, and discarding malformed values. The `url_items` array exposes each URL on its own JSON line for easy extraction.
