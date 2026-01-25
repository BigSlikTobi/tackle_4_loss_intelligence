
import os
import sys
from src.shared.db import get_supabase_client
from src.shared.utils.env import load_env

def check_schema():
    load_env()
    client = get_supabase_client()
    
    schema = "vector_embeddings"
    table = "story_group_members"
    
    print(f"Checking {schema}.{table}...")
    
    # We can't easily get column types via Supabase client directly without some hack or RPC
    # But we can try to insert a dummy record with INT news_url_id and see the error?
    # Or we can try to insert a UUID and see if it works?
    # Actually, the error message "invalid input syntax for type uuid: "2131"" confirms it expects UUID.
    # But let's verify if we can fetch existing rows to see what they look like.
    
    try:
        response = client.schema(schema).table(table).select("*").limit(1).execute()
        if response.data:
            print("Existing row sample:", response.data[0])
        else:
            print("Table is empty.")
            
    except Exception as e:
        print(f"Error fetching: {e}")

if __name__ == "__main__":
    check_schema()
