
import os
import sys
from src.shared.db import get_supabase_client
from src.shared.utils.env import load_env

def check_linkage():
    load_env()
    client = get_supabase_client()
    
    # 1. Fetch a sample from news_urls_embeddings
    print("Fetching sample from vector_embeddings.news_urls_embeddings...")
    try:
        emb_res = client.schema("vector_embeddings").table("news_urls_embeddings").select("*").limit(1).execute()
        if not emb_res.data:
            print("  No data in embeddings table.")
            return
        
        emb_row = emb_res.data[0]
        print(f"  Got row: id={emb_row.get('id')} (type: {type(emb_row.get('id'))}), url={emb_row.get('url')}")
        
        target_url = emb_row.get('url')
        
    except Exception as e:
        print(f"  Error: {e}")
        return

    # 2. Check public.news_urls for this URL
    print(f"\nChecking public.news_urls for url: {target_url}...")
    try:
        # Note: public is default schema
        news_res = client.table("news_urls").select("*").eq("url", target_url).execute()
        
        if news_res.data:
            news_row = news_res.data[0]
            print(f"  MATCH FOUND!")
            print(f"  news_urls.id object: {news_row.get('id')}")
            print(f"  news_urls.id type: {type(news_row.get('id'))}")
            print("  Columns in news_urls:", list(news_row.keys()))
        else:
            print("  NO MATCH FOUND in public.news_urls.")
            
    except Exception as e:
        print(f"  Error checking news_urls: {e}")

if __name__ == "__main__":
    check_linkage()
