# Data Package Contract

The package assembler exposes a stable JSON envelope that downstream systems can consume without mirroring the internal ingestion pipelines. Every response produced by the CLI (`scripts/package_cli.py`) or the Firebase HTTPS function (`functions/main.py`) conforms to the same schema described below.

```json
{
  "schema_version": "1.0.0",
  "package_id": "<hash>",
  "created_at_utc": "2025-02-15T12:34:56Z",
  "producer": "t4l.sports.packager/delivery@1.2.3",
  "subject": { ... },
  "scope": { ... },
  "provenance": { ... },
  "bundles": [ ... ],
  "payload": { ... },
  "links": { ... }
}
```

`package_id` is deterministic: the assembler hashes the subject, scope, bundle metadata, and provenance inputs. Identical requests always yield the same identifier, allowing idempotent writes in downstream stores.

---

## Data stream context

This contract governs **on-demand analytics packages** only. Bundles resolve to providers such as play-by-play, Pro Football Reference, Next Gen Stats, snap counts, FTN charting, and weekly player stats—datasets that are generated at request time and returned inline.

Long-lived warehouse tables (`teams`, `players`, `rosters`, `depth_charts`, `games`) are managed via the loader CLIs under `scripts/data_loaders/` and populate Supabase directly. Those datasets are **not** exposed through this contract or the Firebase HTTP API; consult `README.md` for operational details.

When assembling a package, plan your subject/scope around analytics payloads you want to deliver on demand. If consumers need warehouse data alongside the package, join it after receiving the response from the assembler.

---

## Request schema

Requests submitted to the CLI or HTTP service must be JSON objects with the following top-level fields:

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `schema_version` | string | ✔ | Major/minor contract version. Current tooling supports `"1.0.0"`. |
| `producer` | string | ✔ | Identifier of the caller, typically `<org>/<system>@<version>`. Logged in provenance. |
| `subject` | object | ✔ | Describes the entity or cohort the package is about. |
| `scope` | object | ✔ | Defines temporal and competitive boundaries for the package. |
| `provenance` | object | ✔ | Source and transform metadata. At least one source entry is required. |
| `bundles` | array | ✔ | Collection of bundle specifications describing how to populate the payload. |
| `payload` | object | ✖ | Optional base payload values that bypass provider fetches (useful for pointer bundles or precomputed data). |
| `links` | object | ✖ | Optional hyperlinks or related package descriptors. |

### Subject

```json
"subject": {
  "entity_type": "player" | "team" | "league" | "custom",
  "ids": { "gsis": "00-0036322", "nflverse": "00-0036322", ... },
  "display": { "name": "Justin Jefferson", "team_current": "MIN" }
}
```

- `entity_type` should reflect the logical unit of analysis. When targeting a cohort (for example, multiple players), use a descriptive value such as `"collection"` alongside contextual IDs.
- Populate `ids` with identifiers that downstream systems expect. Keys are free-form; common choices are `gsis`, `nflverse`, `pfr`, or `team_abbr`.
- `display` is returned untouched in the envelope so consumer UIs need not join additional metadata.

### Scope

```json
"scope": {
  "granularity": "week" | "season" | "game" | ...,
  "competition": "regular" | "postseason" | "preseason",
  "temporal": {
    "season": 2023,
    "week": 1,
    "games": ["2023_01_TB_MIN"],
    "date_range_utc": ["2023-09-10", "2023-09-11"]
  },
  "location": {
    "timezone": "UTC",
    "venues": ["US Bank Stadium"]
  }
}
```

Only `season` is mandatory inside `temporal`. Provide `week`, `games`, or `date_range_utc` to narrow the window. `location` is optional.

### Provenance

```json
"provenance": {
  "sources": [
    {"name": "nfl.play_by_play", "version": "2024.01", "fetched_at_utc": "2025-09-10T11:02:00Z"}
  ],
  "transforms": [
    {"name": "normalize_ids", "version": "1.3.0"}
  ],
  "data_quality": {
    "missing_fields": ["air_yards"],
    "assumptions": ["Filtered to active roster only"],
    "row_counts": {"pbp_weekly_player": 11}
  },
  "license_notes": "Data licensed for internal analytics only"
}
```

- At least one entry in `sources` is required and should reflect the upstream dataset feeding the bundle.
- `data_quality` is optional but recommended for transparency. Omit keys whose values would be empty arrays or objects.

### Bundles

Each bundle describes the dataset slice that will populate the payload. Bundles are evaluated in order. Structure:

```json
{
  "name": "pbp_weekly_player",
  "schema_ref": "pbp.events.v1",
  "record_grain": "event",
  "provider": "pbp",
  "filters": { ... },
  "provider_options": { ... },
  "storage_mode": "inlined" | "pointer",
  "pointer": "s3://bucket/path.json",
  "description": "Human readable summary"
}
```

- `provider` must match a registered provider in `src/core/providers/registry.py` (`pbp`, `pfr`, `ftn`, `snap_counts`, `ngs`, ...).
- Use `filters` to constrain provider output. Scalar values trigger equality filters; arrays are treated as inclusive lists. When records expose iterable values (for example, `player_ids`), the assembler looks for any overlap.
- For `storage_mode: "pointer"`, provide `pointer` and omit inline payload data. For inline bundles you may also pre-populate `payload[bundle_name]`; the assembler respects provided data and skips provider execution.
- `provider` entries always map to **on-demand analytics sources**. Static Supabase tables are not valid bundle targets.

### Payload and links

- The assembler populates `payload[bundle.name]` with provider results or merges with any caller-supplied `payload` object.
- Use `links` to reference sibling packages, raw files, or documentation. Each entry is free-form but should contain at least a `type` and `id`/`href`.

---

## Executing a request

### CLI (`scripts/package_cli.py`)

```bash
python3 scripts/package_cli.py --request request.json --pretty
```

Optional arguments:

- `--output /path/to/output.json` writes the envelope to disk.
- `--pretty` toggles an indented JSON response (otherwise the envelope is streamed compactly to stdout).

### Firebase HTTPS function (`functions/main.py`)

`package_handler` expects a `POST` with a JSON body conforming to the schema above. Example cURL request:

```bash
curl -X POST "https://<region>-<project>.cloudfunctions.net/package" \
  -H "Content-Type: application/json" \
  -d @request.json
```

`OPTIONS` requests are handled for CORS preflight, and all responses include permissive `Access-Control-Allow-*` headers for browser clients.

Error handling:

- Invalid JSON → `400` with `{ "error": "Invalid JSON body: ..." }`
- Missing required fields / validation failures → `400` with the validation message emitted by `assemble_package`
- Non-`POST` verbs → `405`
- Unexpected exceptions → `500`

---

## Provider filter expectations

| Provider | Dataset | Common filter keys | Notes |
| --- | --- | --- | --- |
| `pbp` | Play-by-play events | `game_id`, `season`, `week`, `player_id`, `posteam`, `defteam` | Supply `game_id` to target a single matchup. Season/week are inferred from the identifier when omitted. Result rows expose participant IDs (`receiver_player_id`, `rusher_player_id`, etc.) for join operations. |
| `pfr` | Pro Football Reference player-season stats | `season`, `pfr_id` | Optional `stat_type`/`week` filters narrow the returned weekly rows; metrics are grouped under a `metrics` object per record. |
| `player_weekly_stats` | Weekly player stat line | `season`, `week`, `player_id` | Returns numeric stat columns only; descriptive fields are removed for slimmer payloads. |
| `ftn` | FTN play metrics | `season`, `week`, `game_id` | Records are play-level; add joins before filtering by player. |
| `snap_counts` | Player-game snap counts | `pfr_id`, `game_id` | Optional `season`/`week` narrow upstream fetch; payload includes offense/defense/special teams snaps and percentages. |
| `ngs` | Next Gen Stats | `season`, `week`, `player_id` | Provide the desired `stat_type` (for example `receiving`, `rushing`) via `provider_options`; filters enforce non-empty identifiers. |

Filters are applied after transformation and before payload assembly, ensuring the envelope only contains records relevant to the request.

---

## Accessing persisted warehouse datasets

To retrieve canonical rosters, depth charts, game schedules, or team/player master data, run the CLI loaders documented in `README.md`. Each loader writes to Supabase tables and enforces referential integrity across datasets. Because these tables live outside the package contract, any API consumer that needs them should query Supabase (or a replicated warehouse) directly rather than expecting them inside package payloads.

---

## Request patterns & examples

### 1. Single player (play-by-play events)

```json
{
  "schema_version": "1.0.0",
  "producer": "t4l.sports.packager/cli@test",
  "subject": {
    "entity_type": "player",
    "ids": {"gsis": "00-0036322", "nflverse": "00-0036322"},
    "display": {"name": "Justin Jefferson", "team_current": "MIN"}
  },
  "scope": {
    "granularity": "week",
    "competition": "regular",
    "temporal": {"season": 2023, "week": 1},
    "location": {"timezone": "UTC"}
  },
  "provenance": {
    "sources": [{"name": "nfl.play_by_play", "version": "2024.01"}],
    "transforms": [{"name": "normalize_ids"}]
  },
  "bundles": [
    {
      "name": "pbp_weekly_player",
      "schema_ref": "pbp.events.v1",
      "record_grain": "event",
      "provider": "pbp",
      "filters": {"season": 2023, "week": 1, "player_id": "00-0036322"},
      "storage_mode": "inlined",
      "description": "Justin Jefferson targets vs. TB"
    }
  ]
}
```

The resulting payload contains only plays involving the specified player ID.

### 2. Multiple players (same provider)

Supply an array in `filters.player_id` to gather data for a cohort without duplicating bundles.

```json
"filters": {
  "season": 2023,
  "week": 1,
  "player_id": ["00-0036322", "00-0036415"]  // Jefferson + Van Jefferson
}
```

The assembler keeps both players’ records under the same bundle name. Downstream systems can segment on `player_id` inside the payload.

### 3. Single team snapshot

```json
{
  "name": "snap_counts_team",
  "schema_ref": "snap_counts.week.v1",
  "record_grain": "entity",
  "provider": "snap_counts",
  "filters": {"season": 2023, "week": 1, "team": "MIN"},
  "storage_mode": "inlined",
  "description": "Offensive/defensive snaps for the Vikings"
}
```

The subject can remain a player (if the focus is an individual) or shift to `"team"` with the relevant identifiers.

### 4. Multi-team comparison

Use array filters for teams as well:

```json
"filters": {
  "season": 2023,
  "week": 1,
  "team": ["MIN", "GB", "DET"]
}
```

### 5. Mixed bundles (players + teams)

Combine bundles to produce richer packages in a single request:

```json
"bundles": [
  {
    "name": "pbp_jefferson",
    "schema_ref": "pbp.events.v1",
    "record_grain": "event",
    "provider": "pbp",
    "filters": {"season": 2023, "week": 1, "player_id": "00-0036322"},
    "storage_mode": "inlined"
  },
  {
    "name": "snap_counts_vikings",
    "schema_ref": "snap_counts.week.v1",
    "record_grain": "entity",
    "provider": "snap_counts",
    "filters": {"season": 2023, "week": 1, "team": "MIN"},
    "storage_mode": "inlined"
  },
  {
    "name": "pfr_division_rivals",
    "schema_ref": "pfr.week.v1",
    "record_grain": "entity",
    "provider": "pfr",
    "filters": {"season": 2023, "week": 1, "team": ["GB", "DET", "CHI"]},
    "storage_mode": "pointer",
    "pointer": "s3://analytics/pfr/nfc-north-week1.json"
  }
]
```

The assembler returns inline data for the first two bundles and leaves the PFR rival data as a pointer reference.

### 6. Next Gen Stats player week

Request a stat-type-specific NGS payload for a single player-week:

```json
{
  "name": "ngs_player_week",
  "schema_ref": "ngs.player_week.v1",
  "record_grain": "player_week",
  "provider": "ngs",
  "provider_options": {"stat_type": "receiving"},
  "filters": {
    "season": 2025,
    "week": 4,
    "player_id": "00-0036322"
  },
  "storage_mode": "inlined",
  "description": "NGS receiving metrics for Justin Jefferson (2025 Week 4)"
}
```

See `requests/ngs_player_week_package.json` for a complete package envelope that
targets this bundle.

### 7. Pro Football Reference player season

Deliver an entire season of PFR weekly metrics for a single player:

```json
{
  "name": "pfr_player_season",
  "schema_ref": "pfr.player_season.v1",
  "record_grain": "player_week",
  "provider": "pfr",
  "filters": {
    "season": 2025,
    "pfr_id": "JeffJu00"
  },
  "storage_mode": "inlined",
  "description": "PFR weekly metrics for Justin Jefferson (2025 season)"
}
```

`requests/pfr_player_season_package.json` contains a ready-to-run envelope for
testing via the CLI or Firebase function.

### 8. Snap counts player game

Capture snap counts for one player in a specific game:

```json
{
  "name": "snap_counts_player_game",
  "schema_ref": "snap_counts.player_game.v1",
  "record_grain": "player_game",
  "provider": "snap_counts",
  "filters": {
    "season": 2025,
    "pfr_id": "JeffJu00",
    "game_id": "2025_01_MIN_CHI"
  },
  "storage_mode": "inlined",
  "description": "Snap counts for Justin Jefferson vs. CHI (2025 Week 1)"
}
```

See `requests/snap_counts_player_game_package.json` for the complete sample
envelope used by the CLI and Firebase examples.

---

## Tips & validation checklist

1. **Always provide `season` in both `scope.temporal` and bundle filters.** This keeps `package_id` deterministic and avoids pulling cross-season records.
2. **Align identifiers.** If `subject.ids.gsis` is supplied, use the same identifier under `filters.player_id` for player-scoped providers.
3. **Use lists for multi-entity slices.** Arrays are interpreted as “match any of these values”.
4. **Inline payload overrides provider fetch.** Useful when replaying cached data or building packages with out-of-band computations.
5. **Provenance describes the full lineage.** Update `version`, `fetched_at_utc`, and `transforms` whenever upstream inputs change.

---

## Implementation references

- Contract classes: `src/core/contracts/package.py`
- Provider orchestration: `src/core/providers/package_builder.py`
- CLI entry point: `scripts/package_cli.py`
- HTTPS function: `functions/main.py`

These modules encapsulate the logic described above and should remain in sync with this document. Whenever the schema evolves, update both the contract code and this guide before distributing new client instructions.
