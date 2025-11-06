"""
Command-line interface for knowledge extraction.

Extracts topics and entities from story groups and saves to database.
Provides utilities for manual payload testing used by other CLI helpers.
"""

import argparse
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

# Bootstrap to add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from src.shared.utils.logging import setup_logging
from src.shared.utils.env import load_env
from src.functions.knowledge_extraction.core.pipelines.extraction_pipeline import (
    ExtractionPipeline,
)
from src.functions.knowledge_extraction.core.pipelines.batch_pipeline import (
    BatchPipeline,
)
from src.functions.knowledge_extraction.core.db.story_reader import StoryGroupReader
from src.functions.knowledge_extraction.core.extraction.entity_extractor import (
    EntityExtractor,
    ExtractedEntity,
)
from src.functions.knowledge_extraction.core.extraction.topic_extractor import (
    TopicExtractor,
    ExtractedTopic,
)
from src.functions.knowledge_extraction.core.resolution.entity_resolver import (
    EntityResolver,
    ResolvedEntity,
)

logger = logging.getLogger(__name__)


@dataclass
class ManualExtractionResult:
    """Container for manual extraction runs."""

    input_type: Optional[str]
    title: Optional[str]
    text_length: int
    topics: List[ExtractedTopic]
    entities: List[ExtractedEntity]
    resolved_entities: List[ResolvedEntity]
    metadata: Dict[str, Any]

    def summary(self) -> Dict[str, int]:
        """Return high-level counts similar to the pipeline summary."""
        return {
            "topics_extracted": len(self.topics),
            "entities_extracted": len(self.entities),
            "resolved_entities": len(self.resolved_entities),
        }


def _mock_manual_extraction(
    input_type: Optional[str],
    title: Optional[str],
    metadata: Dict[str, Any],
    text_length: int,
) -> ManualExtractionResult:
    """Return deterministic mock output for offline demos."""
    topics = [
        ExtractedTopic(topic="team performance & trends", confidence=0.88, rank=1),
        ExtractedTopic(topic="player profiles & interviews", confidence=0.64, rank=2),
    ]
    entities = [
        ExtractedEntity(
            entity_type="team",
            mention_text="Buffalo Bills",
            team_abbr="BUF",
            confidence=0.86,
            rank=1,
        ),
        ExtractedEntity(
            entity_type="player",
            mention_text="Josh Allen",
            position="QB",
            team_abbr="BUF",
            confidence=0.74,
            rank=2,
        ),
    ]
    resolved_entities = [
        ResolvedEntity(
            entity_type="team",
            entity_id="BUF",
            mention_text="Buffalo Bills",
            matched_name="Buffalo Bills",
            confidence=0.9,
            rank=1,
        ),
        ResolvedEntity(
            entity_type="player",
            entity_id="BUF-QB-J.ALLEN",
            mention_text="Josh Allen",
            matched_name="Josh Allen",
            confidence=0.78,
            rank=2,
            position="QB",
            team_abbr="BUF",
        ),
    ]
    return ManualExtractionResult(
        input_type=input_type,
        title=title,
        text_length=text_length,
        topics=topics,
        entities=entities,
        resolved_entities=resolved_entities,
        metadata=metadata,
    )


def _resolve_manual_entities(
    entities: List[ExtractedEntity],
    resolver: EntityResolver,
) -> List[ResolvedEntity]:
    """Resolve extracted entities using the same logic as the main pipeline."""
    resolved: List[ResolvedEntity] = []
    for entity in entities:
        try:
            resolved_entity = None
            if entity.entity_type == "player":
                resolved_entity = resolver.resolve_player(
                    entity.mention_text,
                    context=entity.context,
                    position=entity.position,
                    team_abbr=entity.team_abbr,
                    team_name=entity.team_name,
                )
            elif entity.entity_type == "team":
                resolved_entity = resolver.resolve_team(
                    entity.mention_text,
                    context=entity.context,
                )
            elif entity.entity_type == "game":
                resolved_entity = resolver.resolve_game(
                    entity.mention_text,
                    context=entity.context,
                )

            if not resolved_entity:
                logger.debug("Unable to resolve %s: %s", entity.entity_type, entity.mention_text)
                continue

            resolved_entity.is_primary = entity.is_primary
            resolved_entity.rank = entity.rank
            if entity.entity_type == "player":
                resolved_entity.position = entity.position
                resolved_entity.team_abbr = entity.team_abbr
                resolved_entity.team_name = entity.team_name

            resolved.append(resolved_entity)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Error resolving entity %s: %s", entity.mention_text, exc)
            continue

    return resolved


def run_manual_extraction(
    payload: Dict[str, Any],
    *,
    max_topics: Optional[int] = None,
    max_entities: Optional[int] = None,
    use_mock: bool = False,
    resolve_entities: bool = True,
) -> ManualExtractionResult:
    """
    Run the knowledge extraction workflow on a manual payload.

    This mirrors the production pipeline logic so other CLI helpers can
    exercise the full extraction flow without touching the database.
    """
    text = (payload.get("text") or "").strip()
    if not text:
        raise ValueError("Manual extraction payload does not contain text to analyse.")

    input_type = payload.get("input_type")
    title = payload.get("title")
    metadata = payload.get("metadata") or {}

    text_length = len(text)

    if use_mock:
        logger.warning("Using mock manual extraction output (no API calls).")
        return _mock_manual_extraction(input_type, title, metadata, text_length)

    if max_topics is None:
        max_topics = int(os.getenv("MAX_TOPICS_PER_GROUP", "10"))
    if max_entities is None:
        max_entities = int(os.getenv("MAX_ENTITIES_PER_GROUP", "20"))

    topic_extractor = TopicExtractor()
    entity_extractor = EntityExtractor()

    topics = topic_extractor.extract(text, max_topics=max_topics)
    entities = entity_extractor.extract(text, max_entities=max_entities)

    resolved_entities: List[ResolvedEntity] = []
    if resolve_entities:
        try:
            resolver = EntityResolver()
            resolved_entities = _resolve_manual_entities(entities, resolver)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Entity resolution unavailable: %s", exc)
            resolved_entities = []

    return ManualExtractionResult(
        input_type=input_type,
        title=title,
        text_length=text_length,
        topics=topics,
        entities=entities,
        resolved_entities=resolved_entities,
        metadata=metadata,
    )


def setup_cli_parser() -> argparse.ArgumentParser:
    """Set up the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Extract topics and entities from NFL story groups.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Check progress
  python extract_knowledge_cli.py --progress

  # Test with dry run (first 5 groups)
  python extract_knowledge_cli.py --dry-run --limit 5

  # Process all unextracted groups (synchronous)
  python extract_knowledge_cli.py

  # Process specific number with verbose logging
  python extract_knowledge_cli.py --limit 10 --verbose

  # BATCH PROCESSING (recommended for large volumes):
  # Create batch job for all unextracted groups (50% cost savings!)
  python extract_knowledge_cli.py --batch

  # Create batch job for specific number with automatic processing
  python extract_knowledge_cli.py --batch --limit 100 --wait

  # Check status of a batch job
  python extract_knowledge_cli.py --batch-status batch_abc123

  # Process completed batch results
  python extract_knowledge_cli.py --batch-process batch_abc123

  # List recent batch jobs
  python extract_knowledge_cli.py --batch-list

Configuration:
  Set OPENAI_API_KEY in environment or .env file
  Optional: MAX_TOPICS_PER_GROUP, MAX_ENTITIES_PER_GROUP
        """,
    )
    
    parser.add_argument(
        "--progress",
        action="store_true",
        help="Show extraction progress statistics and exit",
    )
    
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of story groups to process",
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Extract knowledge but don't write to database",
    )
    
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Retry groups that previously failed extraction",
    )
    
    parser.add_argument(
        "--max-errors",
        type=int,
        default=3,
        help="Maximum error count for retry (default: 3)",
    )
    
    # Batch processing options
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Use batch processing (50%% cost savings, 24h completion)",
    )
    
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Wait for batch to complete and auto-process results (use with --batch)",
    )
    
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=60,
        help="Seconds between status checks when waiting (default: 60)",
    )
    
    parser.add_argument(
        "--batch-status",
        type=str,
        metavar="BATCH_ID",
        help="Check status of a batch job",
    )
    
    parser.add_argument(
        "--batch-process",
        type=str,
        metavar="BATCH_ID",
        help="Process completed batch results",
    )
    
    parser.add_argument(
        "--batch-list",
        action="store_true",
        help="List recent batch jobs",
    )
    
    parser.add_argument(
        "--batch-cancel",
        type=str,
        metavar="BATCH_ID",
        help="Cancel a running batch job",
    )
    
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging (DEBUG level)",
    )
    
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default=None,
        help="Set logging level explicitly",
    )
    
    return parser


def show_progress():
    """Display extraction progress statistics."""
    logger.info("Fetching progress statistics...")
    
    reader = StoryGroupReader()
    stats = reader.get_progress_stats()
    
    if not stats:
        logger.error("Failed to fetch progress statistics")
        return False
    
    print("\n" + "=" * 60)
    print("KNOWLEDGE EXTRACTION PROGRESS")
    print("=" * 60)
    print(f"Total story groups:        {stats.get('total_groups', 0):,}")
    print(f"Groups with extraction:    {stats.get('extracted_groups', 0):,}")
    print(f"Groups remaining:          {stats.get('remaining_groups', 0):,}")
    print(f"Failed groups:             {stats.get('failed_groups', 0):,}")
    print(f"Partial groups:            {stats.get('partial_groups', 0):,}")
    print(f"Processing groups:         {stats.get('processing_groups', 0):,}")
    print(f"\nTotal topics extracted:    {stats.get('total_topics', 0):,}")
    print(f"Total entities extracted:  {stats.get('total_entities', 0):,}")
    print(f"\nAvg topics per group:      {stats.get('avg_topics_per_group', 0)}")
    print(f"Avg entities per group:    {stats.get('avg_entities_per_group', 0)}")
    print("=" * 60)
    print()
    
    if stats.get('failed_groups', 0) > 0:
        print(f"⚠️  {stats['failed_groups']} groups failed - use --retry-failed to retry")
    
    if stats.get('remaining_groups', 0) > 0:
        print(f"💡 Run without --progress flag to extract knowledge for "
              f"{stats['remaining_groups']} remaining groups")
        print(f"💰 Use --batch flag for 50% cost savings on large volumes!")
    else:
        print("✅ All story groups have knowledge extracted!")
    
    return True


def handle_batch_create(args) -> bool:
    """Create a new batch job."""
    try:
        logger.info("Creating batch job...")
        
        pipeline = BatchPipeline()
        
        result = pipeline.create_batch(
            limit=args.limit,
            retry_failed=args.retry_failed,
            max_error_count=args.max_errors,
            wait_for_completion=args.wait,
            poll_interval=args.poll_interval,
        )
        
        if result["status"] == "no_requests":
            logger.warning("No requests to process")
            return False
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to create batch: {e}", exc_info=True)
        return False


def handle_batch_status(batch_id: str) -> bool:
    """Check status of a batch job."""
    try:
        logger.info(f"Checking status for batch: {batch_id}")
        
        pipeline = BatchPipeline()
        status = pipeline.check_status(batch_id)
        
        print("\n" + "=" * 60)
        print("BATCH STATUS")
        print("=" * 60)
        print(f"Batch ID:       {status['batch_id']}")
        print(f"Status:         {status['status']}")
        
        if status.get('request_counts'):
            counts = status['request_counts']
            print(f"\nProgress:")
            print(f"  Total:        {counts.get('total', 0)}")
            print(f"  Completed:    {counts.get('completed', 0)}")
            print(f"  Failed:       {counts.get('failed', 0)}")
            
            total = counts.get('total', 0)
            if total > 0:
                pct = (counts.get('completed', 0) / total) * 100
                print(f"  Complete:     {pct:.1f}%")
        
        if status.get('created_at'):
            from datetime import datetime
            created = datetime.fromtimestamp(status['created_at'])
            print(f"\nCreated at:     {created}")
        
        if status.get('completed_at'):
            completed = datetime.fromtimestamp(status['completed_at'])
            print(f"Completed at:   {completed}")
        
        if status.get('local_info'):
            local = status['local_info']
            print(f"\nLocal info:")
            print(f"  Groups:       {local.get('total_groups', 'N/A')}")
            print(f"  Requests:     {local.get('total_requests', 'N/A')}")
        
        print("=" * 60)
        
        # Show next steps based on status
        if status['status'] == 'completed':
            print(f"\n✅ Batch completed! Process results with:")
            print(f"   python extract_knowledge_cli.py --batch-process {batch_id}")
        elif status['status'] in ['failed', 'expired', 'cancelled']:
            print(f"\n❌ Batch ended with status: {status['status']}")
        else:
            print(f"\n⏳ Batch is {status['status']}. Check again later with:")
            print(f"   python extract_knowledge_cli.py --batch-status {batch_id}")
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to check batch status: {e}", exc_info=True)
        return False


def handle_batch_process(batch_id: str, dry_run: bool) -> bool:
    """Process completed batch results."""
    try:
        logger.info(f"Processing batch results: {batch_id}")
        
        pipeline = BatchPipeline()
        result = pipeline.process_batch(batch_id, dry_run=dry_run)
        
        print("\n" + "=" * 60)
        print("BATCH PROCESSING RESULTS")
        print("=" * 60)
        print(f"Batch ID:           {result['batch_id']}")
        print(f"Groups processed:   {result['groups_processed']}")
        print(f"Topics extracted:   {result['topics_extracted']}")
        print(f"Entities extracted: {result['entities_extracted']}")
        print(f"Groups with errors: {result['groups_with_errors']}")
        print("=" * 60)
        
        if result['errors']:
            print("\nErrors encountered:")
            for error in result['errors'][:10]:
                print(f"  • {error}")
            if len(result['errors']) > 10:
                print(f"  ... and {len(result['errors']) - 10} more")
        
        if dry_run:
            print("\n💡 Remove --dry-run flag to save results to database")
        else:
            print("\n✅ Results saved to database!")
        
        return result['groups_with_errors'] == 0
        
    except Exception as e:
        logger.error(f"Failed to process batch: {e}", exc_info=True)
        return False


def handle_batch_cancel(batch_id: str) -> bool:
    """Cancel a batch job."""
    try:
        logger.info(f"Cancelling batch: {batch_id}")
        
        pipeline = BatchPipeline()
        result = pipeline.cancel_batch(batch_id)
        
        print(f"\n✅ Batch {batch_id} is now {result['status']}")
        print("   (May take up to 10 minutes to fully cancel)")
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to cancel batch: {e}", exc_info=True)
        return False


def handle_batch_list() -> bool:
    """List recent batch jobs."""
    try:
        logger.info("Listing recent batches...")
        
        pipeline = BatchPipeline()
        batches = pipeline.list_batches(limit=10)
        
        print("\n" + "=" * 60)
        print("RECENT BATCH JOBS")
        print("=" * 60)
        
        if not batches:
            print("No batch jobs found")
        else:
            for batch in batches:
                from datetime import datetime
                created = datetime.fromtimestamp(batch['created_at'])
                
                status_emoji = {
                    'completed': '✅',
                    'failed': '❌',
                    'cancelled': '🚫',
                    'in_progress': '⏳',
                    'validating': '🔍',
                }.get(batch['status'], '•')
                
                print(f"\n{status_emoji} {batch['batch_id']}")
                print(f"   Status: {batch['status']}")
                print(f"   Created: {created}")
                
                if batch.get('progress'):
                    print(f"   Progress: {batch['progress']}")
        
        print("=" * 60)
        print("\n💡 Check specific batch with: --batch-status BATCH_ID")
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to list batches: {e}", exc_info=True)
        return False


def main():
    """Main entry point for CLI."""
    parser = setup_cli_parser()
    args = parser.parse_args()
    
    # Load environment
    load_env()
    
    # Set up logging
    if args.log_level:
        log_level = args.log_level
    elif args.verbose:
        log_level = "DEBUG"
    else:
        log_level = "INFO"
    
    setup_logging(level=log_level)
    
    logger.info("=" * 60)
    logger.info("Knowledge Extraction CLI")
    logger.info("=" * 60)
    
    # Show progress and exit if requested
    if args.progress:
        success = show_progress()
        sys.exit(0 if success else 1)
    
    # Validate OpenAI API key
    if not os.getenv("OPENAI_API_KEY"):
        logger.error("OPENAI_API_KEY environment variable not set")
        logger.error("Set it in .env file or export OPENAI_API_KEY=your-key")
        sys.exit(1)
    
    # Handle batch operations
    if args.batch_list:
        handle_batch_list()
        sys.exit(0)
    
    if args.batch_status:
        success = handle_batch_status(args.batch_status)
        sys.exit(0 if success else 1)
    
    if args.batch_process:
        success = handle_batch_process(args.batch_process, args.dry_run)
        sys.exit(0 if success else 1)
    
    if args.batch_cancel:
        success = handle_batch_cancel(args.batch_cancel)
        sys.exit(0 if success else 1)
    
    if args.batch:
        success = handle_batch_create(args)
        sys.exit(0 if success else 1)
    
    # Standard synchronous processing
    # Show configuration
    logger.info(f"Configuration:")
    logger.info(f"  Limit: {args.limit or 'all unextracted groups'}")
    logger.info(f"  Dry run: {args.dry_run}")
    logger.info(f"  Retry failed: {args.retry_failed}")
    if args.retry_failed:
        logger.info(f"  Max errors for retry: {args.max_errors}")
    logger.info(f"  Log level: {log_level}")
    
    max_topics = os.getenv("MAX_TOPICS_PER_GROUP", "10")
    max_entities = os.getenv("MAX_ENTITIES_PER_GROUP", "20")
    logger.info(f"  Max topics per group: {max_topics}")
    logger.info(f"  Max entities per group: {max_entities}")
    
    if args.dry_run:
        logger.warning("🔍 DRY RUN MODE - No data will be written to database")
    
    if args.retry_failed:
        logger.info("🔄 RETRY MODE - Will retry previously failed extractions")
    
    try:
        # Initialize pipeline
        pipeline = ExtractionPipeline()
        
        # Run extraction
        results = pipeline.run(
            limit=args.limit,
            dry_run=args.dry_run,
            retry_failed=args.retry_failed,
            max_error_count=args.max_errors,
        )
        
        # Print summary
        print("\n" + "=" * 60)
        print("EXTRACTION SUMMARY")
        print("=" * 60)
        print(f"Groups processed:      {results['groups_processed']}")
        print(f"Topics extracted:      {results['topics_extracted']}")
        print(f"Entities extracted:    {results['entities_extracted']}")
        print(f"Groups with errors:    {results['groups_with_errors']}")
        print("=" * 60)
        
        if results["errors"]:
            print("\nErrors encountered:")
            for error in results["errors"][:10]:  # Show first 10 errors
                print(f"  • {error}")
            if len(results["errors"]) > 10:
                print(f"  ... and {len(results['errors']) - 10} more")
        
        if args.dry_run:
            print("\n💡 Remove --dry-run flag to save results to database")
        
        # Exit with appropriate code
        if results["groups_with_errors"] > 0:
            sys.exit(1)
        else:
            sys.exit(0)
            
    except KeyboardInterrupt:
        logger.warning("\n\nInterrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Extraction failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
