"""Check story_entities table schema and NYJ data."""
import sys
from pathlib import Path

# Bootstrap
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from src.shared.utils.env import load_env
from src.shared.db.connection import get_supabase_client

load_env()
client = get_supabase_client()

# Get a sample entity to see the actual schema
sample = client.table("story_entities")\
    .select("*")\
    .eq("entity_type", "team")\
    .limit(1)\
    .execute()

if sample.data:
    print("Sample team entity fields:")
    entity = sample.data[0]
    for key, value in entity.items():
        print(f"  {key}: {value}")
else:
    print("No team entities found")

# Check if entity_id field exists with NYJ
print("\n" + "="*60)
print("Checking for NYJ using different fields:")
print("="*60)

# Try entity_id (what the function uses)
try:
    entity_id_count = client.table("story_entities")\
        .select("*", count="exact")\
        .eq("entity_type", "team")\
        .eq("entity_id", "NYJ")\
        .execute()
    print(f"Using entity_id='NYJ': {entity_id_count.count} entities")
except Exception as e:
    print(f"Using entity_id='NYJ': ERROR - {e}")

# Try team_id
try:
    team_id_count = client.table("story_entities")\
        .select("*", count="exact")\
        .eq("entity_type", "team")\
        .eq("team_id", "NYJ")\
        .execute()
    print(f"Using team_id='NYJ': {team_id_count.count} entities")
except Exception as e:
    print(f"Using team_id='NYJ': ERROR - {e}")

# Get a sample NYJ entity if it exists
nyj_sample = client.table("story_entities")\
    .select("*")\
    .eq("entity_type", "team")\
    .eq("team_id", "NYJ")\
    .limit(3)\
    .execute()

if nyj_sample.data:
    print(f"\nSample NYJ team entities:")
    for entity in nyj_sample.data:
        print(f"  story_group_id: {entity.get('story_group_id')}, team_id: {entity.get('team_id')}, entity_id: {entity.get('entity_id')}")
