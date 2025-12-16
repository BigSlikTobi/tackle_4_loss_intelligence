# Fuzzy Search

Isolated module that provides fuzzy matching across the `players`, `teams`, and `games` tables.
Supports Cloud Function and CLI entrypoints with optional filters for each entity type.

## Features
- Fuzzy name matching for players, teams, and games using RapidFuzz.
- Optional filters:
  - Players: `team`, `college`, `position`.
  - Games: `weekday`.
- Pagination-aware Supabase queries for large tables.

## Usage
### CLI
```bash
python -m src.functions.fuzzy_search.scripts.fuzzy_search_cli players "Patrick Mahomes" --team KC --limit 5
python -m src.functions.fuzzy_search.scripts.fuzzy_search_cli teams "Eagles"
python -m src.functions.fuzzy_search.scripts.fuzzy_search_cli games "Chiefs" --weekday Sunday
```

### HTTP (Cloud Function)
```json
{
  "entity_type": "players",
  "query": "Justin Jefferson",
  "player_filters": {"team": "MIN", "position": "WR"},
  "limit": 5
}
```

### Requirements
Install dependencies for this module only:
```bash
pip install -r src/functions/fuzzy_search/requirements.txt
```
