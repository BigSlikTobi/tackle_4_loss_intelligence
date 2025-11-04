"""
LLM-based topic extraction from story summaries.

Extracts key topics and themes from NFL story content.
"""

import logging
import os
import re
import time
from typing import Dict, List, Optional
from dataclasses import dataclass

import openai
from openai import OpenAIError, RateLimitError, APITimeoutError

from ..prompts import build_topic_extraction_prompt

logger = logging.getLogger(__name__)

TOPIC_CATEGORIES: List[str] = [
    "Quarterback Performance & Analysis",
    "Running Back & Rushing Game",
    "Wide Receiver & Passing Game",
    "Defense & Turnovers",
    "Coaching & Play Calling",
    "Injuries & Player Health",
    "Team Performance & Trends",
    "Season Outlook & Predictions",
    "Rookies & Emerging Players",
    "Draft & College Prospects",
    "Trades, Signings & Roster Moves",
    "Contracts & Cap Management",
    "Game Analysis & Highlights",
    "Statistics & Rankings",
    "Fantasy Football Impact",
    "Offseason & Training Camp",
    "Special Teams & Kicking Game",
    "Refereeing & Rules",
    "Player Profiles & Interviews",
    "Team Culture & Leadership",
    "League News & Administration",
    "Off-Field & Lifestyle",
    "Media & Fan Reactions",
]


def normalize_topic_category(label: str) -> str:
    """Normalize a topic label for matching against allowed categories."""
    cleaned = label.lower().strip()
    cleaned = cleaned.replace("&", "and")
    cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned)
    return " ".join(cleaned.split())


TOPIC_CATEGORY_LOOKUP = {
    normalize_topic_category(name): name.lower() for name in TOPIC_CATEGORIES
}


@dataclass
class ExtractedTopic:
    """Represents an extracted topic from story content."""
    
    topic: str  # Normalized topic text (lowercase)
    confidence: Optional[float] = None  # LLM confidence score
    rank: Optional[int] = None  # Importance ranking (1=most important, 2=secondary, etc.)


class TopicExtractor:
    """
    Extracts key topics from NFL story content using LLM.
    
    Topics are normalized and stored as text for cross-referencing.
    Examples: "quarterback performance & analysis", "injuries & player health"
    
    Production features:
    - Exponential backoff retry on rate limits
    - Timeout handling
    - Circuit breaker for consecutive failures
    - Error recovery and logging
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-5-nano",
        max_retries: int = 3,
        timeout: int = 60,
        circuit_breaker_threshold: int = 5
    ):
        """
        Initialize the topic extractor.
        
        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            model: OpenAI model to use for extraction (default: gpt-5-nano)
            max_retries: Maximum retry attempts for failed API calls
            timeout: Request timeout in seconds
            circuit_breaker_threshold: Consecutive failures before circuit opens
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model
        self.max_retries = max_retries
        self.timeout = timeout
        self.circuit_breaker_threshold = circuit_breaker_threshold
        
        if not self.api_key:
            raise ValueError("OpenAI API key required (set OPENAI_API_KEY env var)")
        
        openai.api_key = self.api_key
        
        # Circuit breaker state
        self._consecutive_failures = 0
        self._circuit_open = False
        self._last_failure_time = None
        
        logger.info(
            f"Initialized TopicExtractor with model: {model}, "
            f"max_retries: {max_retries}, timeout: {timeout}s"
        )
    
    def _check_circuit_breaker(self):
        """Check if circuit breaker should prevent API calls."""
        if not self._circuit_open:
            return
        
        # Auto-reset circuit after 5 minutes
        if self._last_failure_time and (time.time() - self._last_failure_time) > 300:
            logger.info("Circuit breaker reset after cooldown period")
            self._circuit_open = False
            self._consecutive_failures = 0
            return
        
        raise Exception(
            f"Circuit breaker is open after {self._consecutive_failures} consecutive failures. "
            "Wait 5 minutes before retrying."
        )
    
    def _record_success(self):
        """Record successful API call."""
        if self._consecutive_failures > 0:
            logger.info("API call succeeded, resetting failure counter")
        self._consecutive_failures = 0
        self._circuit_open = False
    
    def _record_failure(self):
        """Record failed API call and potentially open circuit."""
        self._consecutive_failures += 1
        self._last_failure_time = time.time()
        
        if self._consecutive_failures >= self.circuit_breaker_threshold:
            self._circuit_open = True
            logger.error(
                f"Circuit breaker opened after {self._consecutive_failures} consecutive failures"
            )
    
    def extract(
        self,
        summary_text: str,
        max_topics: int = 6,
    ) -> List[ExtractedTopic]:
        """
        Extract topics from story summary text with retry logic.
        
        Args:
            summary_text: The story summary to analyze
            max_topics: Maximum number of topics to extract
            
        Returns:
            List of ExtractedTopic instances
        """
        logger.debug(f"Extracting topics from summary (length: {len(summary_text)})")
        
        # Check circuit breaker
        try:
            self._check_circuit_breaker()
        except Exception as e:
            logger.error(str(e))
            return []
        
        # Retry loop with exponential backoff
        for attempt in range(self.max_retries):
            try:
                prompt = self._build_extraction_prompt(summary_text, max_topics)
                
                # Use Responses API for GPT-5 models with timeout
                response = openai.responses.create(
                    model=self.model,
                    input=prompt,
                    reasoning={"effort": "medium"},
                    text={"verbosity": "low"},
                    timeout=self.timeout,
                )
                
                topics = self._parse_response(response.output_text)
                self._record_success()
                logger.info(f"Extracted {len(topics)} topics from summary")
                return topics
                
            except RateLimitError as e:
                wait_time = min(2 ** attempt, 60)  # Exponential backoff, max 60s
                logger.warning(
                    f"Rate limit hit (attempt {attempt + 1}/{self.max_retries}). "
                    f"Waiting {wait_time}s before retry..."
                )
                if attempt < self.max_retries - 1:
                    time.sleep(wait_time)
                else:
                    self._record_failure()
                    logger.error(f"Rate limit exceeded after {self.max_retries} attempts")
                    return []
                    
            except APITimeoutError as e:
                logger.warning(
                    f"API timeout (attempt {attempt + 1}/{self.max_retries}): {e}"
                )
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    self._record_failure()
                    logger.error(f"Timeout after {self.max_retries} attempts")
                    return []
                    
            except OpenAIError as e:
                logger.error(
                    f"OpenAI API error (attempt {attempt + 1}/{self.max_retries}): {e}"
                )
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    self._record_failure()
                    return []
                    
            except Exception as e:
                logger.error(f"Unexpected error during extraction: {e}", exc_info=True)
                self._record_failure()
                return []
        
        return []
    
    def _build_extraction_prompt(self, summary_text: str, max_topics: int) -> str:
        """Build the prompt for topic extraction."""
        return build_topic_extraction_prompt(summary_text, max_topics)
    
    def _parse_response(self, response_text: str) -> List[ExtractedTopic]:
        """Parse LLM response into ExtractedTopic objects."""
        import json
        
        try:
            data = json.loads(response_text)
            topics = []
            
            # Handle both formats: {"topics": [...]} or [...]
            if isinstance(data, list):
                topic_list = data
            elif isinstance(data, dict):
                topic_list = data.get("topics", [])
            else:
                logger.error(f"Unexpected response format: {type(data)}")
                return []
            
            for topic_dict in topic_list:
                raw_topic = topic_dict.get("topic", "")
                topic_text = raw_topic.strip()
                
                if not topic_text:
                    logger.warning("Skipping empty topic entry")
                    continue
                
                normalized_key = normalize_topic_category(topic_text)
                canonical_topic = TOPIC_CATEGORY_LOOKUP.get(normalized_key)
                
                if not canonical_topic:
                    logger.warning(
                        "Skipping topic outside allowed categories: %s",
                        topic_text,
                    )
                    continue
                
                topic = ExtractedTopic(
                    topic=canonical_topic,
                    confidence=topic_dict.get("confidence"),
                    rank=topic_dict.get("rank"),
                )
                topics.append(topic)
            
            # Sort topics by rank (ascending: 1, 2, 3...)
            # Topics without rank go to the end
            topics.sort(key=lambda t: t.rank if t.rank is not None else 999)
            
            return topics
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            return []
        except Exception as e:
            logger.error(f"Error parsing topic response: {e}", exc_info=True)
            return []
    
    def extract_batch(
        self,
        summaries: List[Dict[str, str]],
        max_topics_per_summary: int = 10,
    ) -> Dict[str, List[ExtractedTopic]]:
        """
        Extract topics from multiple summaries.
        
        Args:
            summaries: List of dicts with 'id' and 'summary_text' keys
            max_topics_per_summary: Max topics per summary
            
        Returns:
            Dict mapping summary ID to list of extracted topics
        """
        results = {}
        
        for summary in summaries:
            summary_id = summary.get("id")
            summary_text = summary.get("summary_text", "")
            
            if not summary_id or not summary_text:
                logger.warning(f"Skipping invalid summary: {summary}")
                continue
            
            topics = self.extract(summary_text, max_topics_per_summary)
            results[summary_id] = topics
        
        logger.info(f"Extracted topics for {len(results)} summaries")
        return results
