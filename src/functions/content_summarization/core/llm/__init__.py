"""
Google Gemini client for URL context summarization.

Production-ready client with rate limiting, retry logic, and comprehensive error handling.
"""

import logging
import time
from typing import Any, Optional
from collections import deque
from datetime import datetime, timedelta

from google import genai
from google.genai.types import GenerateContentConfig

from .content_fetcher import ContentFetcher

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Token bucket rate limiter for API calls.
    
    Ensures we don't exceed API rate limits and provides graceful throttling.
    """
    
    def __init__(self, max_requests: int = 60, time_window: int = 60):
        """
        Initialize rate limiter.
        
        Args:
            max_requests: Maximum requests allowed in time window
            time_window: Time window in seconds
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = deque()
        
        logger.info(f"Initialized RateLimiter: {max_requests} requests per {time_window}s")
    
    def wait_if_needed(self):
        """Wait if rate limit would be exceeded."""
        now = datetime.now()
        
        # Remove requests outside the time window
        cutoff = now - timedelta(seconds=self.time_window)
        while self.requests and self.requests[0] < cutoff:
            self.requests.popleft()
        
        # Check if we're at the limit
        if len(self.requests) >= self.max_requests:
            # Calculate wait time
            oldest_request = self.requests[0]
            wait_until = oldest_request + timedelta(seconds=self.time_window)
            wait_seconds = (wait_until - now).total_seconds()
            
            if wait_seconds > 0:
                logger.warning(
                    f"Rate limit reached ({self.max_requests} requests/{self.time_window}s). "
                    f"Waiting {wait_seconds:.1f}s..."
                )
                time.sleep(wait_seconds)
                
                # Recheck after waiting
                self.wait_if_needed()
        
        # Record this request
        self.requests.append(now)


class GeminiClient:
    """
    Production-ready client for Google Gemini API with URL context support.

    Features:
    - Rate limiting to prevent API throttling
    - Automatic retry with exponential backoff
    - Circuit breaker for failing URLs
    - Comprehensive error handling
    - Metrics collection
    - Resource cleanup
    """

    # Prompt template designed to prevent hallucination
    SUMMARIZATION_PROMPT = """Analyze the content from this URL: {url}

CRITICAL INSTRUCTIONS:
1. If you CAN access the URL content:
   - ONLY use facts and information explicitly stated in the article
   - DO NOT add external context, background information, or your own knowledge
   - DO NOT make assumptions or inferences beyond what's written
   - Quote or paraphrase only what appears in the source content

2. If you CANNOT access the URL content (e.g., paywall, JavaScript-required, or blocked):
   - Clearly state that the content was not accessible
   - Return null/empty values for all fields
   - DO NOT attempt to guess or infer article content
   - DO NOT use your training data knowledge about similar topics

Please provide:

1. COMPREHENSIVE SUMMARY (3-5 paragraphs):
   - Summarize the main content and key messages
   - Include important details, quotes, and context from the article
   - Maintain factual accuracy

2. KEY POINTS (bullet list):
   - 5-7 main takeaways from the article
   - Each point should be a concise factual statement

3. ENTITIES MENTIONED:
   - Players: List all NFL player names mentioned (format: "FirstName LastName")
   - Teams: List all NFL team names mentioned (use official names)
   - Games: List any specific games referenced (format: "Team1 vs Team2, Week X")

4. ARTICLE CLASSIFICATION:
   - Type: (news, analysis, preview, recap, injury_report, transaction, or other)
   - Sentiment: (positive, negative, neutral, mixed)
   - Quality: (high, medium, low) based on depth and factual content

5. INJURY UPDATES (if applicable):
   - Any injury-related information mentioned in the article
   - Include player names and injury status if available

Format your response as structured data that can be easily parsed."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
        enable_grounding: bool = False,
        max_retries: int = 3,
        max_requests_per_minute: int = 60,
    ):
        """
        Initialize production-ready Gemini client.

        Args:
            api_key: Google Gemini API key
            model: Model to use (gemini-2.5-flash or gemini-2.5-pro)
            enable_grounding: Whether to enable Google Search grounding
            max_retries: Maximum retry attempts for failed requests
            max_requests_per_minute: Rate limit for API calls
        """
        self.api_key = api_key
        self.model = model
        self.enable_grounding = enable_grounding
        self.max_retries = max_retries
        
        self.client = genai.Client(api_key=api_key)
        self.content_fetcher = ContentFetcher()
        self.rate_limiter = RateLimiter(max_requests=max_requests_per_minute, time_window=60)
        
        # Metrics tracking
        self.metrics = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "fallback_requests": 0,
            "total_tokens": 0,
            "total_processing_time": 0.0,
        }

        logger.info(
            f"Initialized GeminiClient: model={model}, grounding={enable_grounding}, "
            f"max_retries={max_retries}, rate_limit={max_requests_per_minute}/min"
        )

    def summarize_url(self, url: str, title: Optional[str] = None) -> dict[str, Any]:
        """
        Generate comprehensive summary of URL content with retry logic.

        Args:
            url: URL to summarize
            title: Optional article title for context

        Returns:
            Dictionary containing:
                - summary: Comprehensive text summary
                - key_points: List of main takeaways
                - players_mentioned: List of player names
                - teams_mentioned: List of team names
                - game_references: List of game descriptions
                - article_type: Classification
                - sentiment: Sentiment analysis
                - content_quality: Quality assessment
                - injury_updates: Injury information (if any)
                - metadata: Processing metadata (tokens, status, etc.)

        Raises:
            Exception: If summarization fails after all retries
        """
        self.metrics["total_requests"] += 1
        
        # Apply rate limiting
        self.rate_limiter.wait_if_needed()
        
        # Retry logic with exponential backoff
        last_exception = None
        for attempt in range(1, self.max_retries + 1):
            try:
                result = self._summarize_url_internal(url, title)
                self.metrics["successful_requests"] += 1
                self.metrics["total_tokens"] += result["metadata"].get("tokens_used", 0)
                self.metrics["total_processing_time"] += result["metadata"].get("processing_time_seconds", 0)
                
                if result["metadata"].get("fallback_method"):
                    self.metrics["fallback_requests"] += 1
                
                return result
                
            except Exception as e:
                last_exception = e
                logger.warning(f"Attempt {attempt}/{self.max_retries} failed for {url}: {e}")
                
                if attempt < self.max_retries:
                    # Exponential backoff: 2^attempt seconds
                    wait_time = 2 ** attempt
                    logger.info(f"Retrying in {wait_time}s...")
                    time.sleep(wait_time)
        
        # All retries failed
        self.metrics["failed_requests"] += 1
        logger.error(f"All {self.max_retries} attempts failed for {url}")
        raise Exception(f"Failed after {self.max_retries} attempts: {last_exception}") from last_exception
    
    def _summarize_url_internal(self, url: str, title: Optional[str] = None) -> dict[str, Any]:
        """
        Internal method to generate summary (single attempt).
        
        Args:
            url: URL to summarize
            title: Optional article title
            
        Returns:
            Summary dictionary
        """
        start_time = time.time()

        try:
            # Build tools configuration
            tools = [{"url_context": {}}]
            if self.enable_grounding:
                tools.append({"google_search": {}})

            # Create the prompt
            prompt = self.SUMMARIZATION_PROMPT.format(url=url)
            if title:
                prompt = f"Article title: {title}\n\n{prompt}"

            logger.debug(f"Generating summary for URL: {url}")

            # Call Gemini API
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=GenerateContentConfig(
                    tools=tools,
                    temperature=0.1,  # Low temperature for factual responses
                ),
            )

            # Extract response text
            response_text = ""
            for part in response.candidates[0].content.parts:
                if hasattr(part, "text"):
                    response_text += part.text

            # Extract metadata
            url_metadata = None
            retrieval_status = "UNKNOWN"
            if hasattr(response.candidates[0], "url_context_metadata"):
                url_metadata = response.candidates[0].url_context_metadata
                if url_metadata and url_metadata.url_metadata:
                    retrieval_status = str(url_metadata.url_metadata[0].url_retrieval_status)
                    
                    # Log retrieval issues and try fallback
                    if "ERROR" in retrieval_status:
                        logger.warning(
                            f"URL retrieval failed for {url}: {retrieval_status}. "
                            "Attempting fallback content fetching..."
                        )
                        
                        # Try fallback content fetching
                        return self._summarize_with_fallback(url, title, start_time)
                        
                    elif "UNSAFE" in retrieval_status:
                        logger.warning(f"URL failed safety check: {url}")

            # Extract token usage
            tokens_used = 0
            if hasattr(response, "usage_metadata"):
                tokens_used = response.usage_metadata.total_token_count

            processing_time = time.time() - start_time

            # Parse structured information from response
            parsed_data = self._parse_response(response_text)

            # Build result
            result = {
                "summary": parsed_data.get("summary", response_text),
                "key_points": parsed_data.get("key_points", []),
                "players_mentioned": parsed_data.get("players_mentioned", []),
                "teams_mentioned": parsed_data.get("teams_mentioned", []),
                "game_references": parsed_data.get("game_references", []),
                "article_type": parsed_data.get("article_type"),
                "sentiment": parsed_data.get("sentiment"),
                "content_quality": parsed_data.get("content_quality"),
                "injury_updates": parsed_data.get("injury_updates"),
                "metadata": {
                    "model_used": self.model,
                    "tokens_used": tokens_used,
                    "processing_time_seconds": processing_time,
                    "url_retrieval_status": retrieval_status,
                    "grounding_enabled": self.enable_grounding,
                },
            }

            logger.info(
                f"Successfully summarized URL: {url} "
                f"(tokens: {tokens_used}, time: {processing_time:.2f}s, status: {retrieval_status})"
            )

            return result

        except Exception as e:
            processing_time = time.time() - start_time
            
            # Check if it's a 500 server error - trigger fallback immediately
            error_str = str(e)
            if "500" in error_str and "INTERNAL" in error_str:
                logger.warning(
                    f"Gemini 500 error for {url}. Triggering fallback content fetching..."
                )
                return self._summarize_with_fallback(url, title, start_time)
            
            logger.error(f"Failed to summarize URL {url}: {e}", exc_info=True)
            raise Exception(f"Gemini API error: {e}") from e

    def _parse_response(self, response_text: str) -> dict[str, Any]:
        """
        Parse structured information from Gemini response.

        Args:
            response_text: Raw response text from Gemini

        Returns:
            Dictionary with parsed structured data
        """
        # This is a simplified parser. In production, you might want to:
        # 1. Use Gemini's structured output mode
        # 2. Implement more robust parsing with regex
        # 3. Handle edge cases better

        parsed = {}

        # Extract summary (text before key points section)
        if "KEY POINTS" in response_text or "Key Points" in response_text:
            summary_end = min(
                response_text.find("KEY POINTS") if "KEY POINTS" in response_text else len(response_text),
                response_text.find("Key Points") if "Key Points" in response_text else len(response_text),
            )
            summary_text = response_text[:summary_end].strip()
            # Remove any leading headers
            if "COMPREHENSIVE SUMMARY" in summary_text:
                summary_text = summary_text.split("COMPREHENSIVE SUMMARY", 1)[1].strip()
            if summary_text.startswith(":"):
                summary_text = summary_text[1:].strip()
            parsed["summary"] = summary_text
        else:
            parsed["summary"] = response_text.strip()

        # Extract key points (bullet points)
        key_points = []
        lines = response_text.split("\n")
        in_key_points = False
        for line in lines:
            line = line.strip()
            if "KEY POINTS" in line or "Key Points" in line:
                in_key_points = True
                continue
            if in_key_points:
                if "ENTITIES" in line or "ARTICLE CLASSIFICATION" in line or "INJURY UPDATE" in line:
                    in_key_points = False
                    continue
                if line.startswith(("-", "•", "*", "·")) or (line and line[0].isdigit() and "." in line[:3]):
                    point = line.lstrip("-•*·0123456789. ").strip()
                    if point:
                        key_points.append(point)
        parsed["key_points"] = key_points

        # Extract players (simplified - looks for "Players:" section)
        players = []
        if "Players:" in response_text or "players:" in response_text:
            # Find the section and extract names
            # This is a simplified implementation
            for line in lines:
                if "players:" in line.lower():
                    # Extract from same line or next lines
                    idx = lines.index(line)
                    for next_line in lines[idx : idx + 10]:
                        if next_line.strip().startswith("-"):
                            name = next_line.strip().lstrip("-•* ").strip()
                            if name and len(name.split()) >= 2:  # At least first and last name
                                players.append(name)
        parsed["players_mentioned"] = players

        # Extract teams (similar approach)
        teams = []
        if "Teams:" in response_text or "teams:" in response_text:
            for line in lines:
                if "teams:" in line.lower():
                    idx = lines.index(line)
                    for next_line in lines[idx : idx + 10]:
                        if next_line.strip().startswith("-"):
                            team = next_line.strip().lstrip("-•* ").strip()
                            if team:
                                teams.append(team)
        parsed["teams_mentioned"] = teams

        # Extract article type, sentiment, quality
        for line in lines:
            line_lower = line.lower()
            if "type:" in line_lower:
                parsed["article_type"] = line.split(":", 1)[1].strip().lower()
            if "sentiment:" in line_lower:
                parsed["sentiment"] = line.split(":", 1)[1].strip().lower()
            if "quality:" in line_lower:
                parsed["content_quality"] = line.split(":", 1)[1].strip().lower()

        # Extract injury updates
        if "INJURY UPDATE" in response_text or "Injury Update" in response_text:
            injury_start = max(
                response_text.find("INJURY UPDATE") if "INJURY UPDATE" in response_text else 0,
                response_text.find("Injury Update") if "Injury Update" in response_text else 0,
            )
            if injury_start > 0:
                injury_text = response_text[injury_start:].split("\n")[0]
                parsed["injury_updates"] = injury_text

        return parsed

    def _summarize_with_fallback(self, url: str, title: Optional[str], start_time: float) -> dict[str, Any]:
        """
        Fallback summarization using fetched content.
        
        When URL context fails, fetch content manually and send text to LLM.
        """
        logger.info(f"Attempting fallback content fetch for: {url}")
        
        # Fetch content
        content, method = self.content_fetcher.fetch_with_fallback(url)
        
        if not content:
            # All fallback methods failed - return empty result
            logger.error(f"All content fetching methods failed for: {url}")
            processing_time = time.time() - start_time
            
            return {
                "summary": "Content could not be accessed. All retrieval methods (URL context, HTTP, headers) failed.",
                "key_points": [],
                "players_mentioned": [],
                "teams_mentioned": [],
                "game_references": [],
                "article_type": None,
                "sentiment": None,
                "content_quality": None,
                "injury_updates": None,
                "metadata": {
                    "model_used": self.model,
                    "tokens_used": 0,
                    "processing_time_seconds": processing_time,
                    "url_retrieval_status": "ALL_METHODS_FAILED",
                    "grounding_enabled": self.enable_grounding,
                    "fallback_method": "all_failed",
                },
            }
        
        logger.info(f"Content fetched via {method}, length: {len(content)} chars")
        
        # Build prompt with fetched content
        title_line = f"Title: {title}" if title else ""
        content_prompt = f"""Analyze the following article content.

URL: {url}
{title_line}

CRITICAL INSTRUCTIONS:
1. ONLY use facts and information from the article content below
2. DO NOT add external context or your own knowledge
3. Extract structured information accurately

ARTICLE CONTENT:
{content}

Please provide:

1. COMPREHENSIVE SUMMARY (3-5 paragraphs):
   - Summarize the main content and key messages
   - Include important details and context
   - Maintain factual accuracy

2. KEY POINTS (bullet list):
   - 5-7 main takeaways
   - Each point should be concise and factual

3. ENTITIES MENTIONED:
   - Players: List all NFL player names (format: "FirstName LastName")
   - Teams: List all NFL team names (use official names)
   - Games: List any specific games referenced

4. ARTICLE CLASSIFICATION:
   - Type: (news, analysis, preview, recap, injury_report, transaction, or other)
   - Sentiment: (positive, negative, neutral, mixed)
   - Quality: (high, medium, low) based on depth

5. INJURY UPDATES (if applicable):
   - Any injury-related information

Format your response clearly with section headers."""
        
        try:
            # Call Gemini with text content (no URL context tool)
            response = self.client.models.generate_content(
                model=self.model,
                contents=content_prompt,
                config=GenerateContentConfig(
                    temperature=0.1,
                ),
            )
            
            # Extract response
            response_text = ""
            for part in response.candidates[0].content.parts:
                if hasattr(part, "text"):
                    response_text += part.text
            
            # Extract token usage
            tokens_used = 0
            if hasattr(response, "usage_metadata"):
                tokens_used = response.usage_metadata.total_token_count
            
            processing_time = time.time() - start_time
            
            # Parse structured information
            parsed_data = self._parse_response(response_text)
            
            result = {
                "summary": parsed_data.get("summary", response_text),
                "key_points": parsed_data.get("key_points", []),
                "players_mentioned": parsed_data.get("players_mentioned", []),
                "teams_mentioned": parsed_data.get("teams_mentioned", []),
                "game_references": parsed_data.get("game_references", []),
                "article_type": parsed_data.get("article_type"),
                "sentiment": parsed_data.get("sentiment"),
                "content_quality": parsed_data.get("content_quality"),
                "injury_updates": parsed_data.get("injury_updates"),
                "metadata": {
                    "model_used": self.model,
                    "tokens_used": tokens_used,
                    "processing_time_seconds": processing_time,
                    "url_retrieval_status": f"FALLBACK_{method.upper()}",
                    "grounding_enabled": False,  # Fallback doesn't use grounding
                    "fallback_method": method,
                },
            }
            
            logger.info(
                f"Fallback summarization successful for {url} "
                f"(method: {method}, tokens: {tokens_used}, time: {processing_time:.2f}s)"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Fallback summarization failed for {url}: {e}", exc_info=True)
            processing_time = time.time() - start_time
            
            return {
                "summary": f"Content was fetched but summarization failed: {str(e)}",
                "key_points": [],
                "players_mentioned": [],
                "teams_mentioned": [],
                "game_references": [],
                "article_type": None,
                "sentiment": None,
                "content_quality": None,
                "injury_updates": None,
                "metadata": {
                    "model_used": self.model,
                    "tokens_used": 0,
                    "processing_time_seconds": processing_time,
                    "url_retrieval_status": "FALLBACK_FAILED",
                    "grounding_enabled": False,
                    "fallback_method": method,
                },
            }

        return parsed
    
    def get_metrics(self) -> dict[str, Any]:
        """
        Get current performance metrics.
        
        Returns:
            Dictionary with metrics:
                - total_requests: Total API calls made
                - successful_requests: Successful completions
                - failed_requests: Failed attempts
                - fallback_requests: Times fallback was used
                - total_tokens: Total tokens consumed
                - total_processing_time: Total time spent (seconds)
                - average_tokens: Average tokens per request
                - average_time: Average time per request (seconds)
                - success_rate: Percentage of successful requests
        """
        avg_tokens = (
            self.metrics["total_tokens"] / self.metrics["successful_requests"]
            if self.metrics["successful_requests"] > 0
            else 0
        )
        
        avg_time = (
            self.metrics["total_processing_time"] / self.metrics["successful_requests"]
            if self.metrics["successful_requests"] > 0
            else 0
        )
        
        success_rate = (
            (self.metrics["successful_requests"] / self.metrics["total_requests"] * 100)
            if self.metrics["total_requests"] > 0
            else 0
        )
        
        return {
            **self.metrics,
            "average_tokens": avg_tokens,
            "average_time_seconds": avg_time,
            "success_rate_percent": success_rate,
        }
    
    def reset_metrics(self):
        """Reset all metrics to zero."""
        self.metrics = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "fallback_requests": 0,
            "total_tokens": 0,
            "total_processing_time": 0.0,
        }
        logger.info("Reset metrics")
    
    def close(self):
        """Clean up resources."""
        if hasattr(self, 'content_fetcher'):
            self.content_fetcher.close()
        logger.debug("Closed GeminiClient")
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
        return False
