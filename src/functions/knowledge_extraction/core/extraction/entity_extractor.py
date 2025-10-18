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
        return f"""You are an expert NFL analyst specialized in entity extraction. Your task is to extract NFL entities from this story summary with STRICT DISAMBIGUATION REQUIREMENTS.

**CRITICAL: Player Disambiguation Rules**
For EVERY player mention, you MUST provide AT LEAST 2 identifying hints:
1. Player name (required)
2. Position (QB, RB, WR, TE, etc.) OR Team (abbreviation like BUF, KC, or full name)

**Why this matters:**
- Multiple players can have the same name (e.g., Josh Allen QB vs Josh Allen LB)
- Without disambiguation, we cannot accurately resolve players to database records
- ONLY extract a player if you can identify AT LEAST 2 hints from the text

**Example Valid Extractions:**
✅ "Josh Allen" + "quarterback" → mention_text: "Josh Allen", position: "QB"
✅ "Josh Allen" + "Bills" → mention_text: "Josh Allen", team_name: "Bills"
✅ "Mahomes" + "Chiefs QB" → mention_text: "Mahomes", position: "QB", team_abbr: "KC"
✅ "Travis Kelce" + "tight end" → mention_text: "Travis Kelce", position: "TE"
✅ "Allen" + "Bills QB" → mention_text: "Allen", position: "QB", team_name: "Bills"

**Example INVALID Extractions (DO NOT EXTRACT):**
❌ "Josh Allen" with no position or team mentioned → SKIP this player
❌ "Allen" alone without position or team → SKIP - needs disambiguation
❌ "Smith" with no position or team → SKIP this player
❌ "the quarterback" with no name → SKIP this reference

**Entity Types to Extract:**

1. **PLAYERS**: Any NFL player mentioned WITH 2+ identifying hints
   - REQUIRED: Player name (full or last name)
   - REQUIRED: Position (QB, RB, WR, TE, etc.) OR Team (abbreviation/full name)
   - OPTIONAL: Additional context for confidence
   - If you cannot find 2+ hints, DO NOT extract the player

2. **TEAMS**: Any NFL team mentioned
   - Use both full names and abbreviations: Kansas City Chiefs, Chiefs, KC
   - Include possessive forms: "Chiefs'", "Chargers'"

3. **GAMES**: Specific matchups or games
   - Include opponent info: "Chiefs vs Chargers", "Sunday Night Football matchup"
   - Include game context: "Week 4 game", "playoff game"

For each entity, provide:
- entity_type: "player", "team", or "game"
- mention_text: The exact name/text as it appears in the summary
- context: A brief phrase showing how it's used (3-5 words)
- is_primary: true if this is the main subject, false if just mentioned
- confidence: Your confidence in this extraction (0.0 to 1.0)
- rank: Importance ranking (1=main subject, 2=secondary, 3=tertiary, etc.)

**RANKING SYSTEM:**
- Rank 1: Main subject(s) of the story - the primary player/team/game being discussed
- Rank 2: Secondary important entities - significantly mentioned or involved
- Rank 3+: Tertiary entities - mentioned but not central to the story

**FOR PLAYERS ONLY - REQUIRED DISAMBIGUATION FIELDS:**
- position: Player position if mentioned (QB, RB, WR, TE, DE, LB, etc.) - use null if not found
- team_abbr: Team abbreviation if mentioned (BUF, KC, SF, etc.) - use null if not found
- team_name: Team full name if mentioned (Bills, Chiefs, 49ers, etc.) - use null if not found

**IMPORTANT:** For players, you MUST provide at least ONE of: position, team_abbr, or team_name.
If you cannot find ANY of these, DO NOT extract the player - skip it entirely.

Return up to {max_entities} entities in JSON format, **ORDERED BY RANK** (rank 1 first, then 2, then 3, etc.):

{{
  "entities": [
    {{
      "entity_type": "player",
      "mention_text": "Josh Allen",
      "context": "throws 3 touchdowns",
      "is_primary": true,
      "confidence": 0.95,
      "rank": 1,
      "position": "QB",
      "team_abbr": "BUF",
      "team_name": "Bills"
    }},
    {{
      "entity_type": "team",
      "mention_text": "Bills",
      "context": "Buffalo Bills offense",
      "is_primary": true,
      "confidence": 0.98,
      "rank": 1,
      "position": null,
      "team_abbr": null,
      "team_name": null
    }},
    {{
      "entity_type": "player",
      "mention_text": "Stefon Diggs",
      "context": "caught 2 TDs",
      "is_primary": false,
      "confidence": 0.90,
      "rank": 2,
      "position": "WR",
      "team_abbr": "BUF",
      "team_name": "Bills"
    }},
    {{
      "entity_type": "team",
      "mention_text": "Dolphins",
      "context": "opponent team",
      "is_primary": false,
      "confidence": 0.95,
      "rank": 2,
      "position": null,
      "team_abbr": null,
      "team_name": null
    }}
  ]
}}

**SUMMARY TO ANALYZE:**

{summary_text}

**Final Reminders:**
- For PLAYERS: Require AT LEAST 2 hints (name + position/team)
- If you only see a player name without position or team, DO NOT extract it
- Be conservative with confidence scores
- Mark only 1-2 entities as primary (main subjects)
- **RANK entities by importance** (1=main subject, 2=secondary, 3+=minor mentions)
- **ORDER the response by rank** (all rank 1 entities first, then rank 2, etc.)
- Capture all name variations when you have sufficient disambiguation info
- For teams and games, disambiguation fields should be null
"""
    
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
