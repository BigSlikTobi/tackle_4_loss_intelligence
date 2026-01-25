import httpx
from typing import Dict, Any, List
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import GenericProxyConfig
from .config import YouTubeSearchRequest, YouTubeSearchResponse, PageInfo


class YouTubeSearchService:
    """Service for searching YouTube videos via the YouTube Data API v3 and fetching transcripts."""
    
    BASE_URL = "https://www.googleapis.com/youtube/v3/search"
    
    @staticmethod
    async def search(request: YouTubeSearchRequest) -> YouTubeSearchResponse:
        """Searches YouTube for videos and optionally fetches transcripts.
        
        Args:
            request: Validated YouTubeSearchRequest with search parameters.
            
        Returns:
            YouTubeSearchResponse with video results.
            
        Raises:
            RuntimeError: If the YouTube API returns an error.
        """
        # Build query parameters
        params: Dict[str, Any] = {
            "part": "snippet",
            "maxResults": request.maxResults,
            "q": request.q,
            "type": request.type,
            "key": request.credentials.key,
        }
        
        # Add optional parameters if provided
        if request.publishedAfter:
            params["publishedAfter"] = request.publishedAfter
        
        if request.videoDuration:
            params["videoDuration"] = request.videoDuration
            
        if request.videoCategoryId:
            params["videoCategoryId"] = request.videoCategoryId
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                YouTubeSearchService.BASE_URL,
                params=params,
                timeout=30.0
            )
            
            if response.status_code != 200:
                error_msg = response.text
                try:
                    error_json = response.json()
                    if "error" in error_json:
                        error_detail = error_json["error"]
                        error_msg = error_detail.get("message", error_msg)
                except Exception:
                    pass
                raise RuntimeError(f"YouTube API Error ({response.status_code}): {error_msg}")
            
            data = response.json()
            items = data.get("items", [])
            
            # Filter by allowed channel titles if specified
            if request.allowedChannelTitles:
                allowed_titles_lower = {title.lower() for title in request.allowedChannelTitles}
                items = [
                    item for item in items 
                    if item.get("snippet", {}).get("channelTitle", "").lower() in allowed_titles_lower
                ]
            
            # Fetch transcripts if requested
            if request.fetchTranscripts:
                YouTubeSearchService._fetch_transcripts_for_items(items, request.proxyUrl)
            
            # Parse and validate response
            try:
                return YouTubeSearchResponse(
                    kind=data.get("kind", "youtube#searchListResponse"),
                    etag=data.get("etag", ""),
                    nextPageToken=data.get("nextPageToken"),
                    prevPageToken=data.get("prevPageToken"),
                    regionCode=data.get("regionCode"),
                    pageInfo=PageInfo(
                        totalResults=data.get("pageInfo", {}).get("totalResults", 0),
                        resultsPerPage=data.get("pageInfo", {}).get("resultsPerPage", 0)
                    ),
                    items=items
                )
            except Exception as e:
                raise RuntimeError(f"Failed to parse YouTube API response: {str(e)}")

    @staticmethod
    def _fetch_transcripts_for_items(items: List[Dict[str, Any]], proxy_url: str = None) -> None:
        """Helper to fetch transcripts for a list of video items in place."""
        # Instantiate API once (not thread safe, but we are in a sync loop here effectively)
        # Configure proxy if provided
        proxy_config = None
        if proxy_url:
            proxy_config = GenericProxyConfig(http_url=proxy_url, https_url=proxy_url)
            
        transcript_api = YouTubeTranscriptApi(proxy_config=proxy_config)
        
        for item in items:
            video_id = item.get("id", {}).get("videoId")
            if not video_id:
                continue
                
            try:
                # v1.2.3: use instance method .fetch() which defaults to english
                # We could expose languages in config if needed.
                transcript_objects = transcript_api.fetch(video_id)
                
                # Convert objects to list of dicts for JSON serialization
                transcript_list = [
                    {
                        "text": t.text,
                        "start": t.start,
                        "duration": t.duration
                    }
                    for t in transcript_objects
                ]
                
                # Combine snippets into one text string
                combined_text = " ".join([t["text"] for t in transcript_list]).strip()
                
                item["transcript"] = combined_text
                item["transcript_snippets"] = transcript_list
            except Exception as e:
                # Log the error for debugging purposes
                print(f"Failed to fetch transcript for {video_id}: {str(e)}")
                # If transcript fails (disabled, not found, etc.), 
                # we simply do not add the 'transcript' field or set as None/empty
                item["transcript"] = None
                item["transcript_snippets"] = None
