"""
DO NOT USE - CURRENTLY IN DEVELOPMENT
Cleanup script to detect and remove author-related facts with optional pagination,
checkpointing, and downstream regeneration controls.
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple

# Add project root to Python path
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from src.shared.db import get_supabase_client
from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging

# Import from sibling script (assuming they are in the same directory)
# We might need to adjust imports if this is run as a module
try:
    from src.functions.content_summarization.scripts.content_pipeline_cli import (
        PipelineConfig,
        build_config,
        create_fact_pooled_embedding,
        handle_easy_article_summary,
        handle_hard_article_summary,
        get_article_difficulty,
        summary_stage_completed,
        mark_news_url_timestamp,
    )
    from src.functions.knowledge_extraction.core.db.knowledge_writer import KnowledgeWriter
except ImportError:
    # Fallback for running directly from scripts dir
    sys.path.append(os.path.dirname(__file__))
    from content_pipeline_cli import (
        PipelineConfig,
        build_config,
        create_fact_pooled_embedding,
        handle_easy_article_summary,
        handle_hard_article_summary,
        get_article_difficulty,
        summary_stage_completed,
        mark_news_url_timestamp,
    )
    from src.functions.knowledge_extraction.core.db.knowledge_writer import KnowledgeWriter

logger = logging.getLogger(__name__)


def _load_checkpoint(checkpoint_path: Optional[str]) -> Dict[str, Any]:
    """Load checkpoint data if available."""
    if not checkpoint_path or not os.path.exists(checkpoint_path):
        return {
            "cursor_id": None,
            "stats": {
                "facts_scanned": 0,
                "facts_flagged": 0,
                "facts_deleted": 0,
                "batches_processed": 0,
            },
            "completed": False,
        }

    try:
        with open(checkpoint_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            data.setdefault("stats", {})
            data["stats"].setdefault("facts_scanned", 0)
            data["stats"].setdefault("facts_flagged", 0)
            data["stats"].setdefault("facts_deleted", 0)
            data["stats"].setdefault("batches_processed", 0)
            data.setdefault("cursor_id", None)
            data.setdefault("completed", False)
            return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load checkpoint %s: %s", checkpoint_path, exc)
        return {
            "cursor_id": None,
            "stats": {
                "facts_scanned": 0,
                "facts_flagged": 0,
                "facts_deleted": 0,
                "batches_processed": 0,
            },
            "completed": False,
        }


def _save_checkpoint(
    checkpoint_path: Optional[str],
    cursor_id: Optional[str],
    stats: Dict[str, int],
    completed: bool,
) -> None:
    """Persist checkpoint data so long runs can resume."""
    if not checkpoint_path:
        return

    payload = {
        "cursor_id": cursor_id,
        "stats": stats,
        "completed": completed,
    }
    tmp_path = f"{checkpoint_path}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        os.replace(tmp_path, checkpoint_path)
    except OSError as exc:
        logger.warning("Unable to write checkpoint %s: %s", checkpoint_path, exc)

AUTHOR_FACT_PATTERNS = [
    # Author/journalist titles and affiliations
    (r'\b(is a|is an)\b.{0,30}\b(reporter|writer|journalist|correspondent|analyst|contributor|editor|columnist)\b.{0,20}\b(for|at|with)\b.{0,20}\b(espn|nfl\.com|cbs|fox|nbc)', "Author affiliation"),
    (r'\b(reporter|writer|journalist|correspondent|analyst|contributor|editor|columnist)\b.{0,20}\b(for|at|with)\b.{0,20}\b(espn|nfl\.com|cbs|fox|nbc)', "Author affiliation"),
    (r'\b(senior|national|lead|staff)\b.{0,20}\b(reporter|writer|journalist|correspondent|analyst)', "Author title"),
    (r'\b(written|reported|coverage) by\b', "Byline"),
    (r'\b(according to|per) (espn|the athletic|nfl\.com|cbs|fox|nbc)\b', "Source attribution"),
    
    # ESPN style: "Name covers the Team at ESPN"
    (r'\b(covers|covering)\b.{0,50}\b(at espn|for espn|at nfl\.com|for nfl\.com)', "Coverage statement"),
    (r'\b(covers|covering)\b.{0,20}\b(beat|nfl|sports)', "Coverage statement"),
    (r'\bcovers\b.{0,20}\b(entire league|whole league|league-wide)', "Coverage statement"),
    (r'\b(previously )?covered\b.{0,50}\b(for|at)\b', "Coverage history"),
    (r'\bcovered the\b.{0,30}\b(for more than|since \d{4})', "Coverage history"),
    
    # Joining/employment statements
    (r'\b(joining|joined)\b.{0,20}\b(espn|nfl\.com|cbs|fox|nbc)', "Employment statement"),
    (r'\bassists with\b.{0,30}\b(coverage|draft|reporting)', "Assistance statement"),
    (r'\bcollege career\b', "Author bio"),

    # Contribution/author bio snippets
    (r'\bcontributes to\b.{0,50}\b(espn|nfl live|get up|sportscenter|countdown|radio)', "Contribution statement"),
    (r'\bis (the )?author of\b', "Author bio"),
    (r'\bis (the )?co-author of\b', "Author bio"),
    (r'\bauthor of two published novels\b', "Author bio"),
    
    # Professional affiliations
    (r'\bmember of the\b.{0,50}\b(board of selectors|hall of fame|association)', "Professional affiliation"),
    
    # Contact/social media
    (r'\b(follow|contact).{0,20}\b(twitter|facebook|instagram|linkedin|email)', "Contact info"),
    
    # Social media and engagement
    (r'\b(follow|subscribe|sign up|join|get).{0,30}\b(newsletter|updates|alerts)', "Engagement CTA"),
    (r'@\w+', "Social media handle"),
    (r'\b(like|share|comment|retweet)\b', "Social media CTA"),
    
    # Website navigation and metadata
    (r'\b(click here|read more|view all|see also|related stories)', "Navigation link"),
    (r'\b(photo credit|image courtesy|getty images)', "Image credit"),
    (r'\b(copyright|©|all rights reserved)', "Copyright notice"),
    (r'\b(terms of service|privacy policy)', "Legal terms"),
    
    # Advertisement and promotional
    (r'\b(advertisement|sponsored|promoted)\b', "Advertisement"),
    (r'\b(download|install) (app|application)', "App promotion"),
    
    # Useless/Metadata Facts
    (r'The current date is \d{4}-\d{2}-\d{2}', "Date metadata"),
    (r'It is Week \d+ of the \d{4} NFL season', "Season metadata"),
    (r'FantasyPros compiled Week \d+ and \d{4} Season Data', "Data compilation metadata"),
    (r'The model simulates every NFL game \d+,?\d* times', "Model simulation stat"),
    (r'The model has been up over \$\d+,?\d* for \$\d+ players', "Betting model stat"),
    
    # Very short or generic statements (likely boilerplate)
    (r'^\w{1,3}$', "Too short"),
]

class AuthorFactCleaner:
    def __init__(self, client, config: PipelineConfig):
        self.client = client
        self.config = config
        self.knowledge_writer = KnowledgeWriter()

    def run(
        self,
        limit: int = 100,
        news_url_id: Optional[str] = None,
        dry_run: bool = False,
        paginate: bool = False,
        checkpoint_path: Optional[str] = None,
        skip_regenerate: bool = False,
        sleep_seconds: float = 0.0,
    ) -> Dict[str, int]:
        """Main execution loop with optional pagination and checkpointing."""
        logger.info(
            "Starting author fact cleanup (batch size=%s, news_url_id=%s, dry_run=%s, paginate=%s, skip_regenerate=%s)",
            limit,
            news_url_id,
            dry_run,
            paginate,
            skip_regenerate,
        )

        checkpoint_data = _load_checkpoint(checkpoint_path)
        cursor_id = checkpoint_data.get("cursor_id")
        stats = checkpoint_data.get("stats", {})
        stats.setdefault("facts_scanned", 0)
        stats.setdefault("facts_flagged", 0)
        stats.setdefault("facts_deleted", 0)
        stats.setdefault("batches_processed", 0)

        # If a prior run was marked complete we start over unless explicitly resumed with cursor
        if checkpoint_data.get("completed") and not cursor_id:
            logger.info("Checkpoint marked complete. Starting a fresh run.")
            stats = {"facts_scanned": 0, "facts_flagged": 0, "facts_deleted": 0, "batches_processed": 0}

        while True:
            facts = self._fetch_facts(limit, news_url_id, cursor_id)
            if not facts:
                logger.info("No more facts returned from Supabase")
                break

            cursor_id = facts[-1]["id"]
            stats["batches_processed"] += 1
            stats["facts_scanned"] += len(facts)

            facts_to_delete, affected_urls = self._identify_author_facts(facts)
            stats["facts_flagged"] += len(facts_to_delete)

            if facts_to_delete:
                logger.info(
                    "Batch summary: scanned=%s flagged=%s urls=%s",
                    len(facts),
                    len(facts_to_delete),
                    len(affected_urls),
                )

                if dry_run:
                    logger.info("[DRY RUN] Skipping deletion/regeneration for this batch")
                else:
                    self._delete_facts(facts_to_delete)
                    stats["facts_deleted"] += len(facts_to_delete)

                    if not skip_regenerate:
                        self._regenerate_urls(affected_urls)
                    else:
                        logger.debug("Skipping regeneration for batch because --skip-regenerate was provided")
            else:
                logger.info("Batch summary: scanned=%s flagged=0", len(facts))

            _save_checkpoint(checkpoint_path, cursor_id, stats, completed=False)

            if not paginate:
                break

            if len(facts) < limit:
                logger.info("Short page (%s facts) indicates completion", len(facts))
                break

            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

        _save_checkpoint(checkpoint_path, cursor_id, stats, completed=True)
        logger.info(
            "Cleanup complete: scanned=%s flagged=%s deleted=%s batches=%s",
            stats["facts_scanned"],
            stats["facts_flagged"],
            stats["facts_deleted"],
            stats["batches_processed"],
        )
        return stats

    def _fetch_facts(
        self,
        limit: int,
        news_url_id: Optional[str] = None,
        cursor_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch facts from DB in deterministic order using keyset pagination."""
        query = self.client.table("news_facts").select("id, news_url_id, fact_text")

        if news_url_id:
            query = query.eq("news_url_id", news_url_id)

        query = query.order("id", desc=False)

        if cursor_id:
            query = query.gt("id", cursor_id)

        response = query.limit(limit).execute()
        return getattr(response, "data", []) or []

    def _identify_author_facts(
        self, facts: List[Dict[str, Any]]
    ) -> Tuple[List[str], Set[str]]:
        """Return matching fact ids and affected URLs for a batch."""
        facts_to_delete: List[str] = []
        affected_urls: Set[str] = set()

        for fact in facts:
            is_author, reason = self._is_author_fact(fact["fact_text"])
            if is_author:
                preview = (fact["fact_text"] or "")[:100]
                logger.info("Found author fact %s (reason: %s)", preview, reason)
                facts_to_delete.append(fact["id"])
                affected_urls.add(fact["news_url_id"])

        return facts_to_delete, affected_urls

    def _is_author_fact(self, fact_text: str) -> Tuple[bool, str]:
        """Use Regex to check if fact is author-related."""
        if not fact_text or not isinstance(fact_text, str):
            return False, "Invalid fact text"
            
        fact_lower = fact_text.lower()
        
        # Check length first
        if len(fact_text) < 15:
            return True, "Too short (< 15 chars)"
            
        for pattern, reason in AUTHOR_FACT_PATTERNS:
            if re.search(pattern, fact_lower, re.IGNORECASE):
                return True, f"Matched pattern: {reason} ({pattern})"
                
        return False, ""

    def _delete_facts(self, fact_ids: List[str]):
        """Delete facts in batches."""
        chunk_size = 100
        for i in range(0, len(fact_ids), chunk_size):
            chunk = fact_ids[i:i + chunk_size]
            self.client.table("news_facts").delete().in_("id", chunk).execute()
            logger.info(f"Deleted batch of {len(chunk)} facts")

    def _regenerate_urls(self, url_ids: Set[str]):
        """Regenerate downstream data for URLs."""
        for url_id in url_ids:
            logger.info(f"Regenerating data for URL: {url_id}")
            try:
                # 1. Regenerate Pooled Embedding
                # First delete old one? create_fact_pooled_embedding checks existence.
                # We should force delete or update.
                self.client.table("story_embeddings").delete().eq("news_url_id", url_id).eq("embedding_type", "fact_pooled").execute()
                create_fact_pooled_embedding(self.client, url_id, self.config)
                
                # 2. Update Metrics (counts, difficulty)
                self.knowledge_writer.update_article_metrics(news_url_id=url_id)
                
                # 3. Regenerate Summaries
                # Check difficulty again as it might have changed
                difficulty_record = get_article_difficulty(self.client, url_id)
                difficulty = difficulty_record.get("article_difficulty")
                
                if difficulty == "easy":
                    handle_easy_article_summary(self.client, url_id, self.config)
                else:
                    handle_hard_article_summary(self.client, url_id, self.config)
                    
                # Update timestamp
                if summary_stage_completed(self.client, url_id):
                    mark_news_url_timestamp(self.client, url_id, "summary_created_at")
                    
            except Exception as e:
                logger.error(f"Failed to regenerate for URL {url_id}: {e}")

def main():
    parser = argparse.ArgumentParser(description="Cleanup author-related facts.")
    parser.add_argument("--limit", type=int, default=100, help="Number of facts to check")
    parser.add_argument("--news-url-id", type=str, help="Specific news URL ID to clean")
    parser.add_argument("--dry-run", action="store_true", help="Don't delete anything")
    parser.add_argument(
        "--paginate",
        action="store_true",
        help="Continue batching through the full table using keyset pagination",
    )
    parser.add_argument(
        "--checkpoint",
        type=str,
        help="Optional checkpoint JSON path for resuming long runs",
    )
    parser.add_argument(
        "--skip-regenerate",
        action="store_true",
        help="Skip downstream regeneration to avoid LLM/API usage",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.0,
        help="Sleep between batches to stay under Supabase rate limits",
    )
    args = parser.parse_args()

    load_env()
    setup_logging()
    
    env = dict(os.environ)
    config = build_config(env)
    client = get_supabase_client()
    
    cleaner = AuthorFactCleaner(client, config)
    cleaner.run(
        limit=args.limit,
        news_url_id=args.news_url_id,
        dry_run=args.dry_run,
        paginate=args.paginate,
        checkpoint_path=args.checkpoint,
        skip_regenerate=args.skip_regenerate,
        sleep_seconds=args.sleep_seconds,
    )

if __name__ == "__main__":
    main()
