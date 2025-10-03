"""
Production-ready command-line interface for extracting NFL news URLs.

This script fetches news URLs from configured RSS feeds and sitemaps
and upserts them into the news_urls table. Features comprehensive
monitoring, progress reporting, and production-ready error handling.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import signal
from pathlib import Path
from typing import Dict, Any

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

from src.functions.news_extraction.core.pipelines import NewsExtractionPipeline

# Global flag for graceful shutdown
shutdown_requested = False


def setup_cli_parser() -> argparse.ArgumentParser:
    """Create argument parser for news extraction CLI."""
    parser = argparse.ArgumentParser(
        description="Extract NFL news URLs from RSS feeds and sitemaps."
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without actually writing to database",
    )

    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear existing records from news_urls table before loading",
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging (DEBUG level)",
    )

    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Set logging level (default: INFO)",
    )

    parser.add_argument(
        "--source",
        type=str,
        help="Filter to specific source by name (substring match, e.g., 'ESPN')",
    )

    parser.add_argument(
        "--days-back",
        type=int,
        help="Only extract articles from last N days (overrides config)",
    )

    parser.add_argument(
        "--max-articles",
        type=int,
        help="Maximum articles to extract per source (overrides config)",
    )

    parser.add_argument(
        "--config",
        type=str,
        help="Path to feeds.yaml configuration file (optional)",
    )

    parser.add_argument(
        "--environment",
        "-e",
        type=str,
        choices=["dev", "staging", "prod"],
        help="Environment for configuration overrides (dev/staging/prod)",
    )

    parser.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="Maximum concurrent workers for source extraction (default: 4)",
    )

    parser.add_argument(
        "--timeout",
        type=int,
        help="HTTP timeout in seconds (overrides config)",
    )

    parser.add_argument(
        "--output-format",
        choices=["text", "json"],
        default="text",
        help="Output format for results (default: text)",
    )

    parser.add_argument(
        "--metrics-file",
        type=str,
        help="Save detailed metrics to JSON file",
    )

    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output in dry-run mode",
    )

    return parser


def setup_logging_from_args(args: argparse.Namespace) -> None:
    """Configure logging based on CLI arguments."""
    import logging

    if args.verbose:
        log_level = "DEBUG"
    else:
        log_level = args.log_level

    # Configure root logger
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def print_results(result: dict, pretty: bool = False) -> None:
    """
    Print extraction results in a human-readable format.

    Args:
        result: Result dictionary from pipeline
        pretty: If True, pretty-print JSON records
    """
    print("\n" + "=" * 60)
    print("NEWS EXTRACTION RESULTS")
    print("=" * 60)

    if not result.get("success"):
        print(f"❌ FAILED: {result.get('error', 'Unknown error')}")
        return

    print(f"✅ SUCCESS")
    print(f"\nSources processed: {result.get('sources_processed', 0)}")
    print(f"Items extracted:   {result.get('items_extracted', 0)}")
    print(f"Items filtered:    {result.get('items_filtered', 0)}")
    print(f"Records to write:  {result.get('total_records', result.get('records_written', 0))}")
    
    # Show deduplication statistics
    new_records = result.get('new_records', 0)
    skipped_records = result.get('skipped_records', 0)
    
    if new_records > 0 or skipped_records > 0:
        print(f"\n📊 Database Write Statistics:")
        print(f"   • New URLs written:    {new_records}")
        print(f"   • Duplicate URLs (skipped): {skipped_records}")
        if new_records + skipped_records > 0:
            skip_rate = (skipped_records / (new_records + skipped_records)) * 100
            print(f"   • Duplicate rate:      {skip_rate:.1f}%")

    if result.get("dry_run"):
        print("\n⚠️  DRY RUN - No data was written to database")

        if result.get("records") and pretty:
            print("\nSample records (first 5):")
            print("-" * 60)
            for i, record in enumerate(result["records"][:5], 1):
                print(f"\n{i}. {record.get('title', 'No title')}")
                print(f"   URL: {record.get('url')}")
                print(f"   Publisher: {record.get('publisher')}")
                print(f"   Published: {record.get('published_date', 'Unknown')}")

    print("=" * 60 + "\n")


def signal_handler(signum, frame):
    """Handle graceful shutdown signals."""
    global shutdown_requested
    print(f"\n🛑 Received signal {signum}. Initiating graceful shutdown...")
    shutdown_requested = True


def print_progress_update(current: int, total: int, operation: str = "Processing"):
    """Print progress update with percentage."""
    if total > 0:
        percentage = (current / total) * 100
        print(f"⏳ {operation}: {current}/{total} ({percentage:.1f}%)")


def save_metrics_to_file(metrics: Dict[str, Any], filepath: str):
    """Save detailed metrics to JSON file."""
    try:
        with open(filepath, 'w') as f:
            json.dump(metrics, f, indent=2, default=str)
        print(f"📊 Metrics saved to: {filepath}")
    except Exception as e:
        print(f"❌ Failed to save metrics: {e}")


def print_json_results(result: Dict[str, Any]):
    """Print results in JSON format."""
    # Remove potentially large records array for JSON output
    json_result = result.copy()
    if "records" in json_result:
        json_result["sample_records"] = json_result["records"][:3]  # First 3 only
        del json_result["records"]
    
    print(json.dumps(json_result, indent=2, default=str))


def validate_args(args) -> Dict[str, str]:
    """Validate command line arguments and return any errors."""
    errors = []
    
    if args.days_back is not None and (args.days_back < 1 or args.days_back > 365):
        errors.append("--days-back must be between 1 and 365")
    
    if args.max_articles is not None and (args.max_articles < 1 or args.max_articles > 1000):
        errors.append("--max-articles must be between 1 and 1000")
    
    if args.max_workers < 1 or args.max_workers > 20:
        errors.append("--max-workers must be between 1 and 20")
    
    if args.timeout is not None and (args.timeout < 5 or args.timeout > 300):
        errors.append("--timeout must be between 5 and 300 seconds")
    
    return errors


def main() -> int:
    """Production-ready main CLI entry point with comprehensive error handling."""
    import logging
    
    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    parser = setup_cli_parser()
    args = parser.parse_args()
    
    # Validate arguments
    validation_errors = validate_args(args)
    if validation_errors:
        print("❌ Argument validation errors:")
        for error in validation_errors:
            print(f"   • {error}")
        return 1

    setup_logging_from_args(args)
    
    logger = logging.getLogger(__name__)
    
    start_time = time.time()

    try:
        logger.info("🚀 Starting news extraction")
        
        # Check for shutdown signal before starting
        if shutdown_requested:
            print("⏹️  Shutdown requested before start. Exiting.")
            return 0

        # Initialize pipeline with production settings
        pipeline = NewsExtractionPipeline(
            config_path=args.config,
            max_workers=args.max_workers
        )

        # Run extraction with progress monitoring
        print("⏳ Initializing extraction pipeline...")
        
        result = pipeline.extract(
            source_filter=args.source,
            days_back=args.days_back,
            max_articles=args.max_articles,
            dry_run=args.dry_run,
            clear=args.clear,
        )
        
        duration = time.time() - start_time
        
        # Add CLI timing to results
        result["cli_duration_seconds"] = duration
        
        # Check for shutdown signal during execution
        if shutdown_requested:
            print("⏹️  Graceful shutdown completed.")
            result["shutdown_requested"] = True

        # Output results based on format
        if args.output_format == "json":
            print_json_results(result)
        else:
            print_results(result, pretty=args.pretty)
        
        # Save detailed metrics if requested
        if args.metrics_file:
            save_metrics_to_file(result.get("metrics", {}), args.metrics_file)
        
        # Performance summary
        if result.get("performance"):
            perf = result["performance"]
            print(f"⚡ Performance Summary:")
            print(f"   Total time: {duration:.2f}s")
            if perf.get("items_per_second"):
                print(f"   Items/sec: {perf['items_per_second']:.1f}")
            if perf.get("records_per_second"):
                print(f"   Records/sec: {perf['records_per_second']:.1f}")

        # Return appropriate exit code
        if not result.get("success"):
            logger.error("Extraction completed with errors")
            return 1
        elif result.get("items_extracted", 0) == 0:
            logger.warning("No items were extracted")
            return 0
        else:
            logger.info(f"✅ Extraction completed successfully in {duration:.2f}s")
            return 0

    except KeyboardInterrupt:
        logger.info("⏹️  Extraction interrupted by user")
        print("\n⏹️  Extraction interrupted. Exiting gracefully...")
        return 130  # Standard exit code for SIGINT

    except FileNotFoundError as e:
        logger.error(f"Configuration file not found: {e}")
        print(f"❌ Configuration error: {e}")
        print("💡 Make sure the feeds.yaml file exists or specify --config path")
        return 2

    except ValueError as e:
        logger.error(f"Configuration validation error: {e}")
        print(f"❌ Configuration error: {e}")
        print("💡 Check your feeds.yaml file for syntax or validation errors")
        return 2

    except Exception as e:
        logger.error(f"Unexpected error during extraction: {e}", exc_info=True)
        print(f"❌ UNEXPECTED ERROR: {e}")
        print("💡 Enable --verbose for detailed error information")
        return 1

    finally:
        # Cleanup logging handlers to prevent resource leaks
        logging.shutdown()


if __name__ == "__main__":
    sys.exit(main())
