# YouTube Search Function

A Cloud Function module that searches YouTube videos via the YouTube Data API v3.

## Features

- Search YouTube videos with customizable parameters
- **Fetch video transcripts** automatically (default: True)
- Filter by publish date, video duration, and category
- Request-scoped credentials (API key passed per request)
- Async HTTP processing for optimal performance

## API Usage

### Request Format

```json
{
  "maxResults": 10,
  "q": "NFL highlights",
  "type": "video",
  "publishedAfter": "2025-12-01T00:00:00Z",
  "videoDuration": "short",
  "videoCategoryId": "17",
  "allowedChannelTitles": ["NFL", "ESPN"],
  "fetchTranscripts": true,
  "proxyUrl": "http://user:pass@proxy.com:8080",
  "credentials": {
    "key": "YOUR_YOUTUBE_API_KEY"
  }
}
```

### Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `maxResults` | Yes | Number of results (1-50) |
| `q` | Yes | Search query string |
| `type` | No | Resource type: `video`, `channel`, `playlist` (default: `video`) |
| `publishedAfter` | No | ISO 8601 datetime filter |
| `videoDuration` | No | Duration filter: `short`, `medium`, `long` |
| `videoCategoryId` | No | YouTube category ID |
| `allowedChannelTitles` | No | List of channel titles to filter results (case-insensitive) |
| `fetchTranscripts` | No | Fetch auto-generated captions (default: `true`) |
| `proxyUrl` | No | Proxy URL for transcript fetching (Required for GCP) |
| `credentials.key` | Yes | YouTube Data API v3 key |

> [!IMPORTANT]
> When deploying to **Google Cloud Functions** or **Cloud Run**, fetching transcripts will fail due to IP blocking by YouTube. You MUST provide a valid `proxyUrl` (e.g., from a residential proxy provider like Webshare) to bypass this restriction.

### Response Format

```json
{
  "kind": "youtube#searchListResponse",
  "etag": "...",
  "nextPageToken": "...",
  "regionCode": "US",
  "pageInfo": {
    "totalResults": 1000000,
    "resultsPerPage": 10
  },
  "items": [
    {
      "kind": "youtube#searchResult",
      "etag": "...",
      "id": {
        "kind": "youtube#video",
        "videoId": "abc123"
      },
      "snippet": {
        "publishedAt": "2025-12-15T10:00:00Z",
        "channelId": "...",
        "title": "Video Title",
        "description": "Video description...",
        "thumbnails": { ... },
        "channelTitle": "Channel Name"
      },
      "transcript": "Welcome back to another video. In today's guide we will...",
      "transcript_snippets": [
        { "text": "Welcome back...", "start": 0.0, "duration": 2.5 },
        { "text": "to another video.", "start": 2.5, "duration": 1.4 }
      ]
    }
  ]
}
```

## Local Development

### Setup

```bash
cd src/functions/youtube_search
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### Run Locally

```bash
cd functions
./run_local.sh
```

### Test with curl

```bash
curl -X POST http://localhost:8080 \
  -H "Content-Type: application/json" \
  -d '{
    "maxResults": 5,
    "q": "test video",
    "type": "video",
    "credentials": {
      "key": "YOUR_YOUTUBE_API_KEY"
    }
  }'
```

## Deployment

```bash
cd functions
./deploy.sh
```

The function will be deployed to Google Cloud Functions. Credentials are supplied within each request (not via environment variables).

## Video Category IDs

Common YouTube video category IDs:

| ID | Category |
|----|----------|
| 1 | Film & Animation |
| 17 | Sports |
| 24 | Entertainment |
| 25 | News & Politics |

See [YouTube API docs](https://developers.google.com/youtube/v3/docs/videoCategories/list) for full list.
