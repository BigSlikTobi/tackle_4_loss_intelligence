"""
Generate batch API request files for knowledge extraction.

Creates .jsonl files with all extraction requests for OpenAI Batch API.
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

from ..db.story_reader import StoryGroupReader

logger = logging.getLogger(__name__)


class BatchRequestGenerator:
    """
    Generates batch API request files for knowledge extraction.
    
    Creates separate requests for topic extraction and entity extraction
    for each story group, formatted according to OpenAI Batch API spec.
    """
    
    def __init__(
        self,
        reader: Optional[StoryGroupReader] = None,
        model: str = "gpt-5-nano",
        max_topics: Optional[int] = None,
        max_entities: Optional[int] = None,
        output_dir: Optional[Path] = None,
    ):
        """
        Initialize the batch request generator.
        
        Args:
            reader: Story group reader (default: new instance)
            model: OpenAI model to use (default: gpt-5-nano)
            max_topics: Max topics per group (default: from env or 10)
            max_entities: Max entities per group (default: from env or 20)
            output_dir: Directory for output files (default: ./batch_files)
        """
        self.reader = reader or StoryGroupReader()
        self.model = model
        self.max_topics = max_topics or int(os.getenv("MAX_TOPICS_PER_GROUP", "10"))
        self.max_entities = max_entities or int(os.getenv("MAX_ENTITIES_PER_GROUP", "20"))
        self.output_dir = output_dir or Path("./batch_files")
        
        # Create output directory
        self.output_dir.mkdir(exist_ok=True)
        
        logger.info(
            f"Initialized BatchRequestGenerator (model={model}, "
            f"max_topics={self.max_topics}, max_entities={self.max_entities})"
        )
    
    def generate(
        self,
        limit: Optional[int] = None,
        retry_failed: bool = False,
        max_error_count: int = 3,
    ) -> Dict:
        """
        Generate batch request file for all unextracted story groups.
        
        Args:
            limit: Maximum number of groups to include (None for all)
            retry_failed: If True, include failed extractions for retry
            max_error_count: Don't retry if error_count exceeds this
            
        Returns:
            Dict with:
                - file_path: Path to generated .jsonl file
                - total_requests: Number of requests in file
                - total_groups: Number of story groups
                - metadata: Additional info about the batch
        """
        logger.info("=" * 80)
        logger.info("Generating Batch Request File")
        logger.info("=" * 80)
        
        # Load unextracted groups
        logger.info(f"Loading groups (limit: {limit or 'all'}, retry_failed: {retry_failed})...")
        groups = self.reader.get_unextracted_groups(
            limit=limit,
            retry_failed=retry_failed,
            max_error_count=max_error_count
        )
        
        if not groups:
            logger.warning("No unextracted groups found")
            return {
                "file_path": None,
                "total_requests": 0,
                "total_groups": 0,
                "metadata": {},
            }
        
        logger.info(f"Generating requests for {len(groups)} story groups...")
        
        # Generate unique filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"knowledge_extraction_batch_{timestamp}.jsonl"
        file_path = self.output_dir / filename
        
        # Generate requests
        requests = []
        groups_included = []
        
        for group in groups:
            group_id = group["id"]
            
            # Load summaries for this group
            summaries = self.reader.get_group_summaries(group_id)
            
            if not summaries:
                logger.warning(f"No summaries found for group {group_id}, skipping")
                continue
            
            # Combine all summary texts
            combined_text = "\n\n".join([
                s.get("summary_text", "") for s in summaries if s.get("summary_text")
            ])
            
            if not combined_text.strip():
                logger.warning(f"No summary text for group {group_id}, skipping")
                continue
            
            # Generate topic extraction request
            topic_request = self._build_topic_request(group_id, combined_text)
            requests.append(topic_request)
            
            # Generate entity extraction request
            entity_request = self._build_entity_request(group_id, combined_text)
            requests.append(entity_request)
            
            groups_included.append(group_id)
        
        # Write to file
        logger.info(f"Writing {len(requests)} requests to {file_path}")
        
        with open(file_path, "w") as f:
            for request in requests:
                f.write(json.dumps(request) + "\n")
        
        # Create metadata file
        metadata = {
            "timestamp": timestamp,
            "model": self.model,
            "total_groups": len(groups_included),
            "total_requests": len(requests),
            "max_topics": self.max_topics,
            "max_entities": self.max_entities,
            "group_ids": groups_included,
            "retry_failed": retry_failed,
            "limit": limit,
        }
        
        metadata_path = self.output_dir / f"knowledge_extraction_batch_{timestamp}_metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)
        
        logger.info("=" * 80)
        logger.info(f"Batch file generated: {file_path}")
        logger.info(f"Total groups: {len(groups_included)}")
        logger.info(f"Total requests: {len(requests)}")
        logger.info(f"Metadata saved: {metadata_path}")
        logger.info("=" * 80)
        
        return {
            "file_path": str(file_path),
            "metadata_path": str(metadata_path),
            "total_requests": len(requests),
            "total_groups": len(groups_included),
            "metadata": metadata,
        }
    
    def _build_topic_request(self, group_id: str, summary_text: str) -> Dict:
        """Build a topic extraction request for batch API."""
        prompt = self._build_topic_extraction_prompt(summary_text, self.max_topics)
        
        return {
            "custom_id": f"topic_{group_id}",
            "method": "POST",
            "url": "/v1/responses",
            "body": {
                "model": self.model,
                "input": prompt,
                "reasoning": {"effort": "medium"},
                "text": {"verbosity": "medium"},
            }
        }
    
    def _build_entity_request(self, group_id: str, summary_text: str) -> Dict:
        """Build an entity extraction request for batch API."""
        prompt = self._build_entity_extraction_prompt(summary_text, self.max_entities)
        
        return {
            "custom_id": f"entity_{group_id}",
            "method": "POST",
            "url": "/v1/responses",
            "body": {
                "model": self.model,
                "input": prompt,
                "reasoning": {"effort": "medium"},
                "text": {"verbosity": "medium"},
            }
        }
    
    def _build_topic_extraction_prompt(self, summary_text: str, max_topics: int) -> str:
        """Build the prompt for topic extraction."""
        return f"""You are an expert NFL analyst specialized in topic extraction. Classify the key NFL themes from this story summary using the STANDARDIZED topic categories below.

**Allowed Topic Categories (return the EXACT category names):**
1. Quarterback Performance & Analysis
2. Running Back & Rushing Game
3. Wide Receiver & Passing Game
4. Defense & Turnovers
5. Coaching & Play Calling
6. Injuries & Player Health
7. Team Performance & Trends
8. Season Outlook & Predictions
9. Rookies & Emerging Players
10. Draft & College Prospects
11. Trades, Signings & Roster Moves
12. Contracts & Cap Management
13. Game Analysis & Highlights
14. Statistics & Rankings
15. Fantasy Football Impact
16. Offseason & Training Camp
17. Special Teams & Kicking Game
18. Refereeing & Rules
19. Player Profiles & Interviews
20. Team Culture & Leadership
21. League News & Administration
22. Off-Field & Lifestyle
23. Media & Fan Reactions

**Guidelines:**
- Return only categories from the list above. Do NOT invent new categories.
- If multiple categories apply, include each as a separate topic ranked by importance.
- Provide at most {max_topics} categories, ordered by rank.
- Avoid player or team names (handled separately as entities).
- Keep confidence between 0 and 1 with two decimal precision.

**RANKING SYSTEM:**
- Rank 1: Primary topic(s) - the main theme/focus of the story
- Rank 2: Secondary topics - important supporting themes
- Rank 3+: Minor topics - mentioned but not central

Return in JSON format, **ORDERED BY RANK** (rank 1 first, then 2, then 3, etc.):

{{
  "topics": [
    {{
      "topic": "quarterback performance & analysis",
      "confidence": 0.95,
      "rank": 1
    }},
    {{
      "topic": "injuries & player health",
      "confidence": 0.90,
      "rank": 1
    }},
    {{
      "topic": "team performance & trends",
      "confidence": 0.85,
      "rank": 2
    }}
  ]
}}

**Story Summary:**

{summary_text}

**Your Response (JSON only):**"""
    
    def _build_entity_extraction_prompt(self, summary_text: str, max_entities: int) -> str:
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

3. **GAMES**: Specific game references
   - Format: "Team1 vs Team2" or with date/week context
   - Include playoff games, rivalries, etc.

**Guidelines:**
- Extract up to {max_entities} entities total
- Include context (surrounding text) for ambiguous mentions
- **RANK entities by importance** (1=main subject, 2=significant, 3+=mentioned)
- Mark is_primary=true for main subjects of the story
- Return JSON format, **ORDERED BY RANK**

**RANKING SYSTEM:**
- Rank 1: Primary entities - main subjects of the story
- Rank 2: Secondary entities - significant mentions
- Rank 3+: Minor entities - mentioned but not central

Return in JSON format:

{{
  "entities": [
    {{
      "entity_type": "player",
      "mention_text": "Josh Allen",
      "position": "QB",
      "team_abbr": "BUF",
      "confidence": 0.95,
      "is_primary": true,
      "rank": 1,
      "context": "Josh Allen threw 3 TDs..."
    }},
    {{
      "entity_type": "team",
      "mention_text": "Bills",
      "confidence": 0.98,
      "is_primary": true,
      "rank": 1,
      "context": "Bills defeated the Chiefs..."
    }}
  ]
}}

**Story Summary:**

{summary_text}

**Your Response (JSON only):**"""
