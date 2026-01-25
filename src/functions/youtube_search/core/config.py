from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class Credentials(BaseModel):
    """YouTube API credentials."""
    key: str = Field(..., description="YouTube Data API v3 key")


class YouTubeSearchRequest(BaseModel):
    """Request model for YouTube Search API call."""
    maxResults: int = Field(..., ge=1, le=50, description="Number of results to return (1-50)")
    q: str = Field(..., description="Search query string")
    type: str = Field("video", description="Resource type: video, channel, or playlist")
    publishedAfter: Optional[str] = Field(None, description="ISO 8601 datetime (e.g., 2025-01-01T00:00:00Z)")
    videoDuration: Optional[str] = Field(None, description="Video duration: short, medium, or long")
    videoCategoryId: Optional[str] = Field(None, description="YouTube video category ID")
    allowedChannelTitles: Optional[List[str]] = Field(None, description="List of allowed channel titles (case-insensitive) for filtering results")
    fetchTranscripts: bool = Field(True, description="Whether to fetch transcripts for videos (default: True)")
    proxyUrl: Optional[str] = Field(None, description="Proxy URL for transcript fetching (required for GCP)")
    credentials: Credentials = Field(..., description="API credentials")


class YouTubeVideoItem(BaseModel):
    """Single video item from search results."""
    kind: str
    etag: str
    id: Dict[str, Any]
    snippet: Optional[Dict[str, Any]] = None


class PageInfo(BaseModel):
    """Pagination info from YouTube API."""
    totalResults: int
    resultsPerPage: int


class YouTubeSearchResponse(BaseModel):
    """Response model from YouTube Search API."""
    kind: str
    etag: str
    nextPageToken: Optional[str] = None
    prevPageToken: Optional[str] = None
    regionCode: Optional[str] = Field(None, description="Region code")
    pageInfo: PageInfo
    items: List[Dict[str, Any]] = Field(..., description="List of video results with optional 'transcript' field")
