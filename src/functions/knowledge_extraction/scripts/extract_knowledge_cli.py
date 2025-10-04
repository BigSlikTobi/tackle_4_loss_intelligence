"""
Command-line interface for knowledge extraction.

Extracts topics and entities from story groups and saves to database.
"""

import argparse
import logging
import sys
from pathlib import Path

# Bootstrap to add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from src.shared.utils.logging import setup_logging
from src.shared.utils.env import load_env
from src.functions.knowledge_extraction.core.pipelines.extraction_pipeline import (
    ExtractionPipeline,
)
from src.functions.knowledge_extraction.core.db.story_reader import StoryGroupReader

logger = logging.getLogger(__name__)


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

  # Process all unextracted groups
  python extract_knowledge_cli.py

  # Process specific number with verbose logging
  python extract_knowledge_cli.py --limit 10 --verbose

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
    else:
        print("✅ All story groups have knowledge extracted!")
    
    return True


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
    import os
    if not os.getenv("OPENAI_API_KEY"):
        logger.error("OPENAI_API_KEY environment variable not set")
        logger.error("Set it in .env file or export OPENAI_API_KEY=your-key")
        sys.exit(1)
    
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
