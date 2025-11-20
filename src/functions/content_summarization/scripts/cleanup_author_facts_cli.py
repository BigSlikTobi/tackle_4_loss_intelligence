"""
Cleanup script to detect and remove author-related facts and regenerate downstream data.
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from collections import defaultdict
from typing import Any, Dict, List, Set, Tuple

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
        call_llm_json,
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
        call_llm_json,
        create_fact_pooled_embedding,
        handle_easy_article_summary,
        handle_hard_article_summary,
        get_article_difficulty,
        summary_stage_completed,
        mark_news_url_timestamp,
    )
    from src.functions.knowledge_extraction.core.db.knowledge_writer import KnowledgeWriter

logger = logging.getLogger(__name__)

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

    def run(self, limit: int = 100, news_url_id: str = None, dry_run: bool = False):
        """Main execution loop."""
        logger.info(f"Starting author fact cleanup (Limit: {limit}, News URL ID: {news_url_id}, Dry Run: {dry_run})")
        
        # 1. Fetch candidate facts
        facts = self._fetch_facts(limit, news_url_id)
        logger.info(f"Fetched {len(facts)} facts to analyze")
        
        facts_to_delete = []
        affected_urls = set()
        
        for fact in facts:
            is_author, reason = self._is_author_fact(fact["fact_text"])
            if is_author:
                logger.info(f"Found author fact: {fact['fact_text'][:100]}...")
                logger.info(f"  Reason: {reason}")
                facts_to_delete.append(fact["id"])
                affected_urls.add(fact["news_url_id"])
        
        logger.info(f"Identified {len(facts_to_delete)} facts to delete across {len(affected_urls)} URLs")
        
        if not facts_to_delete:
            return

        if dry_run:
            logger.info("[DRY RUN] Skipping deletion and regeneration")
            return

        # 2. Delete facts (Cascades to embeddings, topics, entities)
        self._delete_facts(facts_to_delete)
        
        # 3. Regenerate downstream data for affected URLs
        self._regenerate_urls(affected_urls)

    def _fetch_facts(self, limit: int, news_url_id: str = None) -> List[Dict[str, Any]]:
        """Fetch facts from DB."""
        query = self.client.table("news_facts").select("id, news_url_id, fact_text")
        
        if news_url_id:
            query = query.eq("news_url_id", news_url_id)
        
        response = (
            query
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return getattr(response, "data", []) or []

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
    args = parser.parse_args()

    load_env()
    setup_logging()
    
    env = dict(os.environ)
    config = build_config(env)
    client = get_supabase_client()
    
    cleaner = AuthorFactCleaner(client, config)
    cleaner.run(limit=args.limit, news_url_id=args.news_url_id, dry_run=args.dry_run)

if __name__ == "__main__":
    main()
