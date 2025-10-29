"""
LLM-based entity extraction from story summaries.

Extracts mentions of players, teams, and games from NFL story content.
"""

import logging
import os
import time
from typing import Dict, List, Optional
from dataclasses import dataclass

import openai
from openai import OpenAIError, RateLimitError, APITimeoutError

from ..prompts import build_entity_extraction_prompt

logger = logging.getLogger(__name__)


@dataclass
class ExtractedEntity:
    """Represents an extracted entity from story content."""
    
    entity_type: str  # 'player', 'team', 'game'
    mention_text: str  # Original text from story
    context: Optional[str] = None  # Surrounding context
    confidence: Optional[float] = None  # LLM confidence score
    is_primary: bool = False  # Main subject vs. mention
    rank: Optional[int] = None  # Importance ranking (1=most important, 2=secondary, etc.)
    
    # Player-specific disambiguation fields
    position: Optional[str] = None  # QB, RB, WR, etc.
    team_abbr: Optional[str] = None  # BUF, KC, etc.
    team_name: Optional[str] = None  # Bills, Chiefs, etc.


class EntityExtractor:
    """
    Extracts NFL entities (players, teams, games) from story content using LLM.
    
    Uses OpenAI GPT-5-nano reasoning model to identify and extract entity mentions with context.
    
    Player Disambiguation:
    - Requires 2+ identifying hints per player (name + position/team)
    - Examples: "Josh Allen" requires "QB" or "Bills" to disambiguate
    - Reduces false positives from players with common names
    
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
        Initialize the entity extractor.
        
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
            f"Initialized EntityExtractor with model: {model}, "
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
        max_entities: int = 20,
    ) -> List[ExtractedEntity]:
        """
        Extract entities from story summary text with retry logic.
        
        Args:
            summary_text: The story summary to analyze
            max_entities: Maximum number of entities to extract
            
        Returns:
            List of ExtractedEntity instances
        """
        logger.debug(f"Extracting entities from summary (length: {len(summary_text)})")
        
        # Check circuit breaker
        try:
            self._check_circuit_breaker()
        except Exception as e:
            logger.error(str(e))
            return []
        
        # Retry loop with exponential backoff
        for attempt in range(self.max_retries):
            try:
                prompt = self._build_extraction_prompt(summary_text, max_entities)
                
                # Use Responses API for GPT-5 models with timeout
                response = openai.responses.create(
                    model=self.model,
                    input=prompt,
                    reasoning={"effort": "medium"},
                    text={"verbosity": "low"},
                    timeout=self.timeout,
                )
                
                entities = self._parse_response(response.output_text)
                self._record_success()
                logger.info(f"Extracted {len(entities)} entities from summary")
                return entities
                
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
    
    def _build_extraction_prompt(self, summary_text: str, max_entities: int) -> str:
        """Build the prompt for entity extraction."""
        return build_entity_extraction_prompt(summary_text, max_entities)

    def _parse_response(self, response_text: str) -> List[ExtractedEntity]:
        """Parse LLM response into ExtractedEntity objects."""
        import json
        
        try:
            data = json.loads(response_text)
            entities = []
            
            for entity_dict in data.get("entities", []):
                entity_type = entity_dict.get("entity_type", "").lower()
                mention_text = entity_dict.get("mention_text", "")
                position = entity_dict.get("position")
                team_abbr = entity_dict.get("team_abbr")
                team_name = entity_dict.get("team_name")
                
                # Validate entity type
                if entity_type not in ("player", "team", "game"):
                    logger.warning(f"Invalid entity_type: {entity_type}, skipping")
                    continue
                
                # Validate mention text
                if not mention_text or len(mention_text.strip()) == 0:
                    logger.warning("Empty mention_text, skipping")
                    continue
                
                # CRITICAL: Validate player disambiguation
                if entity_type == "player":
                    # Check for disambiguation fields
                    has_position = position is not None and len(str(position).strip()) > 0
                    has_team_abbr = team_abbr is not None and len(str(team_abbr).strip()) > 0
                    has_team_name = team_name is not None and len(str(team_name).strip()) > 0
                    
                    # Require at least one disambiguation field
                    if not (has_position or has_team_abbr or has_team_name):
                        logger.warning(
                            f"Player '{mention_text}' missing disambiguation info "
                            "(position, team_abbr, or team_name required), skipping"
                        )
                        continue
                    
                    logger.debug(
                        f"Player '{mention_text}' validated with: "
                        f"position={position}, team_abbr={team_abbr}, team_name={team_name}"
                    )
                
                entity = ExtractedEntity(
                    entity_type=entity_type,
                    mention_text=mention_text,
                    context=entity_dict.get("context"),
                    confidence=entity_dict.get("confidence"),
                    is_primary=entity_dict.get("is_primary", False),
                    rank=entity_dict.get("rank"),
                    position=position if entity_type == "player" else None,
                    team_abbr=team_abbr if entity_type == "player" else None,
                    team_name=team_name if entity_type == "player" else None,
                )
                
                entities.append(entity)
            
            # Sort entities by rank (ascending: 1, 2, 3...)
            # Entities without rank go to the end
            entities.sort(key=lambda e: e.rank if e.rank is not None else 999)
            
            return entities
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            return []
        except Exception as e:
            logger.error(f"Error parsing entity response: {e}", exc_info=True)
            return []
    
    def extract_batch(
        self,
        summaries: List[Dict[str, str]],
        max_entities_per_summary: int = 20,
    ) -> Dict[str, List[ExtractedEntity]]:
        """
        Extract entities from multiple summaries.
        
        Args:
            summaries: List of dicts with 'id' and 'summary_text' keys
            max_entities_per_summary: Max entities per summary
            
        Returns:
            Dict mapping summary ID to list of extracted entities
        """
        results = {}
        
        for summary in summaries:
            summary_id = summary.get("id")
            summary_text = summary.get("summary_text", "")
            
            if not summary_id or not summary_text:
                logger.warning(f"Skipping invalid summary: {summary}")
                continue
            
            entities = self.extract(summary_text, max_entities_per_summary)
            results[summary_id] = entities
        
        logger.info(f"Extracted entities for {len(results)} summaries")
        return results
