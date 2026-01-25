"""
CLI script to sync data from a live Supabase instance to a local/dev instance.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import List, Dict, Any

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from src.functions.data_loading.core.utils.cli import (
    setup_cli_parser,
    setup_cli_logging,
    handle_cli_errors,
    confirm_action,
)
from src.shared.utils.env import load_env
from src.shared.db.connection import get_supabase_client, SupabaseConfig
import logging

logger = logging.getLogger(__name__)

@handle_cli_errors
def main() -> bool:
    # Load environment variables first
    load_env()
    
    parser = setup_cli_parser(
        description="Sync data from Live (Source) Supabase to Local (Target) Supabase."
    )
    parser.add_argument(
        "--tables",
        nargs="+",
        required=True,
        help="List of tables to sync (e.g. --tables teams games players)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Number of records to fetch per table (default: 100). Ignored if --all is set.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Fetch ALL records from the table (paginated).",
    )
    parser.add_argument(
        "--wipe",
        action="store_true",
        help="Wipe the target table before writing new data",
    )
    
    args = parser.parse_args()
    setup_cli_logging(args)

    # 1. Setup Source Client (Prod/Live) - uses partial env vars by default if not passed
    # The default get_supabase_client uses SUPABASE_URL and SUPABASE_KEY from env
    logger.info("Connecting to Source (Live) Supabase...")
    try:
        source_client = get_supabase_client()
    except Exception as e:
        logger.error(f"Failed to connect to Source Supabase: {e}")
        return False

    # 2. Setup Target Client (Dev/Local) - strictly from SUPABASE_URL_DEV / SUPABASE_KEY_DEV
    dev_url = os.getenv("SUPABASE_URL_DEV")
    dev_key = os.getenv("SUPABASE_KEY_DEV")
    
    if not dev_url or not dev_key:
        logger.error("Missing SUPABASE_URL_DEV or SUPABASE_KEY_DEV in environment.")
        return False
        
    logger.info("Connecting to Target (Local) Supabase...")
    try:
        target_config = SupabaseConfig(url=dev_url, key=dev_key)
        target_client = get_supabase_client(target_config)
    except Exception as e:
        logger.error(f"Failed to connect to Target Supabase: {e}")
        return False

    if args.dry_run:
        logger.info("DRY RUN: No changes will be made to target database.")

    for table_input in args.tables:
        logger.info(f"Processing: {table_input}")
        
        # Parse schema if present (e.g. "content.articles" -> schema="content", table="articles")
        if "." in table_input:
            schema, table_name = table_input.split(".", 1)
        else:
            schema = "public" # Default schema
            table_name = table_input

        # a. Fetch from Source (Paginated)
        target_count = "ALL" if args.all else args.limit
        logger.info(f"  Fetching records from Source [{schema}.{table_name}] (Target: {target_count})...")
        
        all_data = []
        page_size = 1000
        offset = 0
        
        try:
            # Configure source query with correct schema and ordering
            # We assume 'created_at' exists as per requirement
            source_query = source_client.schema(schema).table(table_name).select("*").order("created_at", desc=True)
            
            while True:
                # determine how many to fetch in this batch
                if args.all:
                    # just fetch full pages until empty
                    current_limit = page_size
                else:
                    # fetch up to remaining limit
                    remaining = args.limit - len(all_data)
                    if remaining <= 0:
                        break
                    current_limit = min(page_size, remaining)

                # Fetch batch
                # Note: .range() is inclusive: range(0, 9) returns 10 items
                end = offset + current_limit - 1
                
                # Re-construct query for each page to apply range
                # (Supabase/Postgrest client often requires fresh builder or clone)
                # We need to apply ordering here too
                batch_response = source_client.schema(schema).table(table_name).select("*").order("created_at", desc=True).range(offset, end).execute()
                batch = batch_response.data
                
                if not batch:
                    break
                    
                all_data.extend(batch)
                offset += len(batch)
                
                logger.debug(f"    Fetched batch: {len(batch)} records (Total: {len(all_data)})")
                
                # If we got less than requested, we are done
                if len(batch) < current_limit:
                    break
                    
            logger.info(f"  Fetched Total: {len(all_data)} records from Source.")
            
        except Exception as e:
            logger.error(f"  Failed to fetch from table '{schema}.{table_name}': {e}")
            continue

        if not all_data:
            logger.warning(f"  No data found in source table '{schema}.{table_name}'. Skipping.")
            continue

        if args.dry_run:
            if args.wipe:
                logger.info(f"  [DRY RUN] Would wipe table '{schema}.{table_name}' in Target.")
            logger.info(f"  [DRY RUN] Would upsert {len(all_data)} records into '{schema}.{table_name}' in Target.")
            continue

        # b. Wipe Target if requested
        if args.wipe:
            logger.info(f"  Wiping table '{schema}.{table_name}' in Target...")
            try:
                # Determine ID type from fetched data to properly format the delete filter
                wipe_val = 0
                if all_data and "id" in all_data[0]:
                    first_id = all_data[0]["id"]
                    if isinstance(first_id, str):
                        # Assume UUID or string ID
                        wipe_val = "00000000-0000-0000-0000-000000000000"
                
                # Use schema-aware client
                target_client.schema(schema).table(table_name).delete().neq("id", wipe_val).execute()
                logger.info("  Wipe command completed (assuming 'id' column exists).")
            except Exception as e:
                logger.warning(f"  Could not wipe table '{schema}.{table_name}': {e}")
                # Fallback: try the other type if first attempt failed? 
                # e.g. if we guessed int but it was UUID (fetched data might differ from target schema?)
                # For now, just logging warning is safer than infinite retries.

        # c. Upsert
        logger.info(f"  Upserting {len(all_data)} records to Target...")
        total_upserted = 0
        upsert_batch_size = 1000
        
        for i in range(0, len(all_data), upsert_batch_size):
            batch = all_data[i : i + upsert_batch_size]
            try:
                # Try batch upsert first (fast)
                target_client.schema(schema).table(table_name).upsert(batch).execute()
                total_upserted += len(batch)
            except Exception as batch_error:
                logger.warning(f"  Batch upsert failed: {batch_error}")
                logger.warning("  Falling back to individual upserts for this batch...")
                
                # Fallback: Upsert one by one
                for record in batch:
                    try:
                        target_client.schema(schema).table(table_name).upsert(record).execute()
                        total_upserted += 1
                    except Exception as row_error:
                        record_id = record.get("id", "unknown")
                        # Log error but continue
                        logger.error(f"  Failed to upsert record {record_id}: {row_error}")
        
        logger.info(f"  Successfully upserted {total_upserted} records.")

    logger.info("Sync operation completed.")
    return True

if __name__ == "__main__":
    main()
