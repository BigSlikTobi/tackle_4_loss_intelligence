"""
CLI script to sync data from Source (Live/Prod) to Target (Local/Dev) Supabase instance.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from src.functions.data_loading.core.utils.cli import (
    setup_cli_parser,
    setup_cli_logging,
    handle_cli_errors,
    print_results,
    confirm_action
)
from src.shared.db.connection import get_supabase_client, SupabaseConfig

logger = logging.getLogger(__name__)

def sync_table(
    source_client,
    target_client,
    table_input: str,
    args: argparse.Namespace
) -> Dict[str, Any]:
    """Sync a single table from source to target."""
    # Parse schema.table
    if "." in table_input:
        schema, table_name = table_input.split(".", 1)
    else:
        schema = "public"
        table_name = table_input

    logger.info(f"Syncing table: {schema}.{table_name}")
    
    # 1. Fetch data from source
    records = []
    
    query = source_client.schema(schema).table(table_name).select("*").order("created_at", desc=True)
    
    if args.all:
        logger.info(f"Fetching ALL records for {table_name}...")
        offset = 0
        limit = 1000  # Batch size for reading
        while True:
            logger.debug(f"Fetching range {offset} to {offset + limit - 1}...")
            response = query.range(offset, offset + limit - 1).execute()
            batch = response.data
            if not batch:
                break
            records.extend(batch)
            if len(batch) < limit:
                break
            offset += limit
    else:
        logger.info(f"Fetching top {args.limit} records for {table_name}...")
        response = query.range(0, args.limit - 1).execute()
        records = response.data

    logger.info(f"Fetched {len(records)} records from source.")

    if not records:
        return {"success": True, "messages": [f"No records found in {table_name}."]}

    if args.dry_run:
        return {
            "success": True,
            "would_upsert": len(records),
            "would_clear": table_name if args.wipe else None,
            "messages": [f"Would sync {len(records)} records for {table_name}"]
        }

    # 2. Wipe if requested
    if args.wipe:
        logger.warning(f"Wiping table {schema}.{table_name} on target...")
        try:
            # Check if table is empty or has records
            existing = target_client.schema(schema).table(table_name).select("*").limit(1).execute()
            if not existing.data:
                logger.info(f"Table {table_name} is already empty.")
            else:
                # Check for 'id' column
                first_record = existing.data[0]
                if 'id' in first_record:
                    # Safe wipe using ID filter
                    # We use a filter that matches everything non-null usually, or just NEQ to a value that doesn't exist.
                    # For UUIDs or Ints, '0000...' or -1 might work, but NEQ 'safe_wipe_marker' is string-based.
                    # Best generic way for Supabase: .neq('id', '00000000-0000-0000-0000-000000000000') works for UUIDs
                    # For Ints, we might need a different strategy.
                    # Let's try checking type of ID? 
                    # Actually, let's just use NOT IS NULL if possible, or `gt` -1 for int, `neq` null for others.
                    # Supabase-py / PostgREST syntax for "not is null": .not_.is_('id', 'null')
                    target_client.schema(schema).table(table_name).delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
                    logger.info(f"Wiped table {table_name}.")
                else:
                    logger.error(f"Cannot wipe table {table_name}: No 'id' column found. Manual truncation required.")
        except Exception as e:
            logger.error(f"Failed to wipe table {table_name}: {e}")

    # 3. Upsert to target
    logger.info(f"Upserting {len(records)} records to target...")
    
    try:
        # Try batch upsert
        target_client.schema(schema).table(table_name).upsert(records).execute()
        logger.info(f"Successfully batch upserted {len(records)} records.")
    except Exception as e:
        logger.warning(f"Batch upsert failed: {e}. Switching to individual upserts.")
        success_count = 0
        fail_count = 0
        for record in records:
            try:
                target_client.schema(schema).table(table_name).upsert(record).execute()
                success_count += 1
            except Exception as inner_e:
                logger.error(f"Failed to upsert record {record.get('id', '?')}: {inner_e}")
                fail_count += 1
        logger.info(f"Individual upsert complete. Success: {success_count}, Failed: {fail_count}")

    return {
        "success": True, 
        "records_processed": len(records),
        "records_written": len(records)  # distinct from 'upserted' which is unknown in batch
    }


@handle_cli_errors
def main():
    # Load environment variables first
    load_dotenv()
    
    parser = setup_cli_parser("Sync data from Live to Local Supabase")
    
    # Custom args
    parser.add_argument("--tables", nargs="+", required=True, help="List of tables to sync")
    parser.add_argument("--limit", type=int, default=10, help="Number of records to fetch (default: 10)")
    parser.add_argument("--wipe", action="store_true", help="Wipe local table before writing (Caution!)")
    parser.add_argument("--all", action="store_true", help="Fetch ALL records (ignores --limit)")
    
    args = parser.parse_args()
    setup_cli_logging(args)

    # 1. Connect to Source (Prod)
    logger.info("Connecting to SOURCE (Prod)...")
    source_config = SupabaseConfig.from_env(
        url_var="SUPABASE_URL",
        key_var="SUPABASE_KEY"
    )
    source_client = get_supabase_client(source_config)

    # 2. Connect to Target (Dev/Local)
    logger.info("Connecting to TARGET (Dev)...")
    target_config = SupabaseConfig.from_env(
        url_var="SUPABASE_URL_DEV",
        key_var="SUPABASE_KEY_DEV"
    )
    target_client = get_supabase_client(target_config)

    # 3. Sync Tables
    results = {}
    for table in args.tables:
        try:
            res = sync_table(source_client, target_client, table, args)
            results[table] = res
            print_results(res, operation=f"Sync {table}", dry_run=args.dry_run)
        except Exception as e:
            logger.error(f"Failed to sync table {table}: {e}")
            results[table] = {"success": False, "error": str(e)}

    return results

if __name__ == "__main__":
    main()
