# This script fetches and inspects facts associated with a given news URL ID.
# It writes the retrieved facts to a local text file for review.

import argparse
import os
import sys
from pathlib import Path

# Add project root to Python path
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from src.shared.db import get_supabase_client
from src.shared.utils.env import load_env

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("news_url_id", help="UUID of the news URL")
    args = parser.parse_args()

    load_env()
    client = get_supabase_client()

    response = (
        client.table("news_facts")
        .select("fact_text")
        .eq("news_url_id", args.news_url_id)
        .execute()
    )

    facts = getattr(response, "data", []) or []
    with open("facts_dump.txt", "w") as f:
        f.write(f"Found {len(facts)} facts:\n")
        for i, fact in enumerate(facts):
            f.write(f"{i+1}. {fact['fact_text']}\n")
    print(f"Wrote {len(facts)} facts to facts_dump.txt")

if __name__ == "__main__":
    main()
