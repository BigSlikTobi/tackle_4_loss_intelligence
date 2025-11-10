# Injury Loader Overview

The injury loader is implemented in [`injuries.py`](./injuries.py) and is built around the shared `DatasetPipeline` abstraction.
It is composed of three main stages:

1. **Fetch** – `fetch_injury_data` retrieves the raw weekly injury report data for the requested `season`, `week`, and
   optional `season_type`.
2. **Transform** – `InjuryDataTransformer` normalises the payload and resolves the shape required for persistence.
3. **Write** – `InjurySupabaseWriter` performs an upsert into the `injuries` table in Supabase using the conflict columns
  `(season, week, season_type, team_abbr, player_id)` and annotates each ingestion with a monotonically increasing
  `version` number plus an `is_current` flag.

### Player resolution

Before writing, the loader attempts to resolve each record to an internal `player_id`. When a `player_id` is not provided in
the scraped data, the writer looks up the player inside the cached `players` table using display name, first/last name
combinations, and the most recent team. Records that cannot be resolved are skipped and reported in the pipeline result.

### Versioned persistence and current markers

* Every pipeline execution first looks up the latest `version` stored for the `(season, week, season_type)` scope being
  ingested and assigns the next sequential number to the new batch. All rows written in the same run therefore share the
  same `version` value.
* Newly written rows are tagged with `is_current = true`. Immediately after the upsert completes, the writer marks prior
  versions for the same scope as `is_current = false` so downstream consumers can filter out stale data while the historical
  state remains queryable.
* The writer **still does not delete** rows; historic versions are preserved with an older version number and `is_current =
  false`.

When querying Supabase, prefer `is_current = true` (or the highest `version`) to read the most recent injury snapshot while
keeping the ability to analyse older reports when needed.

#### Database requirements

To support versioning the Supabase `injuries` table must expose two additional columns:

```sql
alter table injuries
    add column if not exists version integer not null default 1,
    add column if not exists is_current boolean not null default true;

create index if not exists injuries_scope_version_idx
    on injuries (season, week, season_type, version);

create index if not exists injuries_scope_current_idx
    on injuries (season, week, season_type, is_current);
```

The writer validates the presence of these columns before ingesting a batch and raises a descriptive error if the schema has
not been upgraded yet. Existing data can be backfilled by setting `version = 1` and `is_current = true` for the latest report
per `(season, week, season_type)` scope while marking older rows as `is_current = false`.
