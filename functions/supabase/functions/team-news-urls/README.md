# Team News URLs Edge Function

Returns every news URL associated with a specific team abbreviation from the past 24 hours. The function looks up `story_entities` for the provided `team_abbr`, resolves their `story_group_members`, and finally fetches the corresponding `news_urls` records so we can return both the URL and its `created_at` timestamp.

## Deployment

```bash
cd functions
supabase functions deploy team-news-urls
```

## Invocation

```bash
supabase functions invoke team-news-urls --query "team_abbr=KC"
```

### Query Parameters

- `team_abbr` *(required)*: Team abbreviation used to resolve story groups (case-insensitive, converted to upper-case before querying).
- `max_urls` *(optional)*: Maximum number of URLs to return. Default `TEAM_NEWS_MAX_URLS` env (200).
- `timeout_ms` *(optional)*: Request timeout in milliseconds. Default `TEAM_NEWS_TIMEOUT_MS` env (10000).
- `concurrency` *(optional)*: Parallel worker count used while fetching URLs. Default `TEAM_NEWS_CONCURRENCY` env (4).
- `TEAM_NEWS_LOOKBACK_HOURS` *(env)*: Lookback window applied to `story_entities`, `story_group_members`, and `news_urls`. Defaults to 24 hours.

## Response

```json
{
  "team_abbr": "KC",
  "count": 2,
  "urls": [
    "https://example.com/story-one",
    "https://example.com/story-two"
  ],
  "url_items": [
    { "url": "https://example.com/story-one", "created_at": "2024-05-10T14:31:22.123Z" },
    { "url": "https://example.com/story-two", "created_at": "2024-05-10T12:18:05.991Z" }
  ]
}
```

The response deduplicates and normalizes URLs (scheme/host lowercased, whitespace trimmed) while preserving each record's `created_at` timestamp. When no recent story groups or URLs exist for the provided team abbreviation, the function returns an empty list with `count: 0`.
