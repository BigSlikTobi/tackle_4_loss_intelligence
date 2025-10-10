"""
CLI tool for content summarization.

Provides command-line interface for generating content summaries from news URLs.
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Bootstrap: Add project root to Python path
from _bootstrap import configure_path
configure_path()

from src.shared.utils.env import load_env
from src.shared.utils.logging import setup_logging
from src.functions.content_summarization.core.db import NewsUrlReader, SummaryWriter
from src.functions.content_summarization.core.llm import GeminiClient
from src.functions.content_summarization.core.pipelines import SummarizationPipeline

logger = logging.getLogger(__name__)


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate content summaries from news URLs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry-run mode (no database writes)
  python summarize_cli.py --dry-run --limit 5

  # Process all unsummarized URLs
  python summarize_cli.py --limit 10

  # Process specific publisher
  python summarize_cli.py --publisher ESPN --limit 5

  # Process specific URLs
  python summarize_cli.py --url-ids 123,456,789

  # Enable grounding for fact-checking
  python summarize_cli.py --enable-grounding --limit 5

  # Verbose logging
  python summarize_cli.py --verbose --limit 3
        """
    )

    # Core options
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without writing to database (for testing)"
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of URLs to process (default: 10)"
    )

    # Selection modes
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--publisher",
        type=str,
        help="Process URLs from specific publisher (e.g., ESPN, ProFootballTalk)"
    )

    selection.add_argument(
        "--url-ids",
        type=str,
        help="Comma-separated list of news_url IDs to process"
    )

    # LLM options
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Override Gemini model (default: from GEMINI_MODEL env var)"
    )

    parser.add_argument(
        "--enable-grounding",
        action="store_true",
        help="Enable Google Search grounding for fact-checking"
    )

    # Execution options
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Stop processing on first error (default: continue)"
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging (DEBUG level)"
    )

    return parser.parse_args()


def main():
    """Main CLI entry point."""
    args = parse_args()

    # Load environment variables
    load_env()

    # Setup logging
    log_level = "DEBUG" if args.verbose else "INFO"
    setup_logging(level=log_level)

    logger.info("=== Content Summarization CLI ===")

    # Validate environment
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY not found in environment")
        sys.exit(1)

    model = args.model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash-preview-09-2025")

    # Display configuration
    logger.info(f"Configuration:")
    logger.info(f"  Model: {model}")
    logger.info(f"  Grounding: {'Enabled' if args.enable_grounding else 'Disabled'}")
    logger.info(f"  Dry-run: {args.dry_run}")
    logger.info(f"  Limit: {args.limit}")
    logger.info(f"  Stop on error: {args.stop_on_error}")

    if args.publisher:
        logger.info(f"  Publisher filter: {args.publisher}")
    elif args.url_ids:
        url_ids = [x.strip() for x in args.url_ids.split(",")]
        logger.info(f"  URL IDs: {url_ids}")

    # Initialize components
    try:
        reader = NewsUrlReader()
        writer = SummaryWriter(dry_run=args.dry_run)
        llm_client = GeminiClient(
            api_key=api_key,
            model=model,
            enable_grounding=args.enable_grounding
        )
        pipeline = SummarizationPipeline(
            gemini_client=llm_client,
            url_reader=reader,
            summary_writer=writer,
            continue_on_error=not args.stop_on_error
        )

        logger.info("Components initialized successfully")

    except Exception as e:
        logger.error(f"Failed to initialize components: {e}")
        sys.exit(1)

    # Execute pipeline based on mode
    try:
        logger.info("Starting processing...")

        if args.url_ids:
            # Process specific URLs
            url_ids = [x.strip() for x in args.url_ids.split(",")]
            stats = pipeline.process_by_ids(url_ids=url_ids)
        elif args.publisher:
            # Process by publisher
            stats = pipeline.process_by_publisher(
                publisher_name=args.publisher,
                limit=args.limit
            )
        else:
            # Process unsummarized URLs
            stats = pipeline.process_unsummarized_urls(limit=args.limit)

        # Display results
        logger.info("=== Processing Complete ===")
        logger.info(f"Total URLs: {stats['total']}")
        logger.info(f"Successful: {stats['successful']}")
        logger.info(f"Failed: {stats['failed']}")
        logger.info(f"Skipped: {stats['skipped']}")

        if stats["errors"]:
            logger.warning(f"Errors encountered: {len(stats['errors'])}")
            for error in stats["errors"][:5]:  # Show first 5 errors
                logger.warning(f"  - {error}")
            if len(stats["errors"]) > 5:
                logger.warning(f"  ... and {len(stats['errors']) - 5} more")

        # Display detailed summary for successful operations
        if stats["successful"] > 0:
            print("\n" + "=" * 80)
            print("📊 SUMMARY RESULTS")
            print("=" * 80)
            
            # Get the summaries that were just created
            try:
                # Re-fetch to get the summaries (in dry-run, this won't work, so we skip)
                if not args.dry_run and stats["successful"] > 0:
                    from src.functions.content_summarization.core.contracts import ContentSummary
                    from src.shared.db.connection import get_supabase_client
                    
                    supabase = get_supabase_client()
                    # Get recent summaries (last hour)
                    from datetime import datetime, timedelta
                    one_hour_ago = (datetime.utcnow() - timedelta(hours=1)).isoformat()
                    
                    summary_response = (
                        supabase.table("context_summaries")
                        .select("*, news_url:news_urls(url, title)")
                        .gte("created_at", one_hour_ago)
                        .order("created_at", desc=True)
                        .limit(stats["successful"])
                        .execute()
                    )
                    
                    for idx, summary_data in enumerate(summary_response.data, 1):
                        print(f"\n{'─' * 80}")
                        print(f"Summary #{idx}")
                        print(f"{'─' * 80}")
                        
                        # URL Info
                        news_url = summary_data.get("news_url", [{}])[0] if summary_data.get("news_url") else {}
                        print(f"🔗 URL: {news_url.get('url', 'N/A')}")
                        if news_url.get("title"):
                            print(f"📰 Title: {news_url['title']}")
                        
                        # Metadata
                        print(f"\n📋 Metadata:")
                        print(f"  • Article Type: {summary_data.get('article_type', 'N/A')}")
                        print(f"  • Sentiment: {summary_data.get('sentiment', 'N/A')}")
                        print(f"  • Content Quality: {summary_data.get('content_quality', 'N/A')}")
                        
                        # Processing Info
                        print(f"\n🤖 Processing:")
                        print(f"  • Model: {summary_data.get('model_used', 'N/A')}")
                        print(f"  • Tokens Used: {summary_data.get('tokens_used', 0):,}")
                        print(f"  • Processing Time: {summary_data.get('processing_time_seconds', 0):.2f}s")
                        print(f"  • URL Retrieval: {summary_data.get('url_retrieval_status', 'N/A')}")
                        print(f"  • Grounding: {'Enabled' if args.enable_grounding else 'Disabled'}")
                        
                        # Entities
                        if summary_data.get('players_mentioned') or summary_data.get('teams_mentioned'):
                            print(f"\n👥 Entities Extracted:")
                            if summary_data.get('players_mentioned'):
                                print(f"  • Players: {', '.join(summary_data['players_mentioned'][:5])}")
                                if len(summary_data['players_mentioned']) > 5:
                                    print(f"    ... and {len(summary_data['players_mentioned']) - 5} more")
                            if summary_data.get('teams_mentioned'):
                                print(f"  • Teams: {', '.join(summary_data['teams_mentioned'])}")
                        
                        # Key Points
                        if summary_data.get('key_points'):
                            print(f"\n🔑 Key Points:")
                            for point in summary_data['key_points'][:5]:
                                print(f"  • {point}")
                            if len(summary_data['key_points']) > 5:
                                print(f"  ... and {len(summary_data['key_points']) - 5} more")
                        
                        # Summary
                        summary_text = summary_data.get('summary', '')
                        if summary_text:
                            print(f"\n📝 Summary:")
                            # Wrap text at 76 characters
                            import textwrap
                            wrapped = textwrap.fill(summary_text, width=76, initial_indent="  ", subsequent_indent="  ")
                            # Limit to first 300 characters for display
                            if len(summary_text) > 300:
                                print(wrapped[:300] + "...")
                                print(f"  [Full summary: {len(summary_text)} characters]")
                            else:
                                print(wrapped)
                        
                        # Injury Updates
                        if summary_data.get('injury_updates'):
                            print(f"\n🏥 Injury Updates:")
                            print(f"  {summary_data['injury_updates']}")
                
                elif args.dry_run:
                    # In dry-run mode, show the generated summaries
                    print(f"\n[DRY-RUN MODE] - No summaries written to database")
                    print(f"\nConfiguration:")
                    print(f"  • Model: {model}")
                    print(f"  • Grounding: {'Enabled' if args.enable_grounding else 'Disabled'}")
                    print(f"  • URLs Processed: {stats['successful']}")
                    
                    # Display generated summaries
                    if stats.get('summaries'):
                        import textwrap
                        for idx, summary in enumerate(stats['summaries'], 1):
                            print(f"\n{'─' * 80}")
                            print(f"Summary #{idx}")
                            print(f"{'─' * 80}")
                            
                            # Processing Info
                            print(f"\n🤖 Processing:")
                            print(f"  • Model: {summary.model_used}")
                            print(f"  • Tokens Used: {summary.tokens_used:,}")
                            print(f"  • Processing Time: {summary.processing_time_seconds:.2f}s")
                            print(f"  • URL Retrieval: {summary.url_retrieval_status}")
                            print(f"  • Grounding: {'Enabled' if args.enable_grounding else 'Disabled'}")
                            
                            # Metadata
                            if summary.article_type or summary.sentiment or summary.content_quality:
                                print(f"\n📋 Metadata:")
                                if summary.article_type:
                                    print(f"  • Article Type: {summary.article_type}")
                                if summary.sentiment:
                                    print(f"  • Sentiment: {summary.sentiment}")
                                if summary.content_quality:
                                    print(f"  • Content Quality: {summary.content_quality}")
                            
                            # Entities
                            if summary.players_mentioned or summary.teams_mentioned:
                                print(f"\n👥 Entities Extracted:")
                                if summary.players_mentioned:
                                    print(f"  • Players: {', '.join(summary.players_mentioned[:5])}")
                                    if len(summary.players_mentioned) > 5:
                                        print(f"    ... and {len(summary.players_mentioned) - 5} more")
                                if summary.teams_mentioned:
                                    print(f"  • Teams: {', '.join(summary.teams_mentioned)}")
                            
                            # Key Points
                            if summary.key_points:
                                print(f"\n🔑 Key Points:")
                                for point in summary.key_points[:5]:
                                    print(f"  • {point}")
                                if len(summary.key_points) > 5:
                                    print(f"  ... and {len(summary.key_points) - 5} more")
                            
                            # Summary
                            if summary.summary:
                                print(f"\n📝 Summary:")
                                wrapped = textwrap.fill(summary.summary, width=76, initial_indent="  ", subsequent_indent="  ")
                                print(wrapped)
                            
                            # Injury Updates
                            if summary.injury_updates:
                                print(f"\n🏥 Injury Updates:")
                                print(f"  {summary.injury_updates}")
                        
                        print(f"\n{'─' * 80}")
                        print(f"\n✓ Successfully generated {len(stats['summaries'])} summaries")
                        print(f"  Run without --dry-run to save to database")
                    elif stats['successful'] > 0:
                        print(f"\n✓ Successfully generated {stats['successful']} summaries")
                        print(f"  Run without --dry-run to save to database")
                
            except Exception as e:
                logger.debug(f"Could not fetch detailed summaries: {e}")
                # Fall back to basic summary
                print(f"\nConfiguration:")
                print(f"  • Model: {model}")
                print(f"  • Grounding: {'Enabled' if args.enable_grounding else 'Disabled'}")
                print(f"  • URLs Processed: {stats['successful']}")
            
            print("\n" + "=" * 80)

        # Exit with appropriate code
        if stats["failed"] > 0:
            sys.exit(1)
        else:
            sys.exit(0)

    except KeyboardInterrupt:
        logger.info("Processing interrupted by user")
        sys.exit(130)

    except Exception as e:
        logger.error(f"Processing failed: {e}", exc_info=args.verbose)
        sys.exit(1)


if __name__ == "__main__":
    main()
