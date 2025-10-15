# Game Analysis Package - Technical Guide

## Overview

The Game Analysis Package is a production-ready Cloud Function that transforms raw NFL play-by-play data into enriched, AI-ready analysis packages. It processes **complete games** (120-180 plays) in single requests, automatically identifies key players, enriches player metadata using **nflreadpy**, computes comprehensive statistics, and produces both detailed datasets and compact LLM-optimized summaries.

**Deployment Status**: ✅ Production (Revision 00021-duk)  
**Cloud Function URL**: https://game-analysis-hjm4dt4a5q-uc.a.run.app  
**Runtime**: Python 3.11, 512MB memory, 60s timeout  
**Region**: us-central1 (Google Cloud)

## Architecture

### Function-Based Isolation

This module follows the platform's **function-based isolation** architecture:

- **Complete Independence**: Develops, tests, and deploys without affecting other modules
- **Isolated Dependencies**: Own `requirements.txt` and virtual environment
- **Separate Deployment**: Independent Cloud Function
- **Minimal Coupling**: Only uses generic utilities from `src/shared/`

### Module Structure

```
src/functions/game_analysis_package/
├── core/                              # All business logic
│   ├── contracts/                     # Data contracts & types
│   │   ├── game_package.py            # Input validation
│   │   ├── analysis_envelope.py       # LLM output format
│   │   └── enriched_package.py        # Full data structure
│   ├── extraction/                    # Player identification
│   │   ├── player_extractor.py        # Extract player IDs
│   │   └── relevance_scorer.py        # Score & select players
│   ├── fetching/                      # Data fetching services
│   │   ├── play_fetcher.py            # Fetch plays from database
│   │   └── player_metadata_enricher.py # Enrich with nflreadpy
│   ├── processing/                    # Data transformation
│   │   ├── game_summarizer.py         # Compute statistics
│   │   └── envelope_builder.py        # Create AI summaries
│   ├── pipeline/                      # Orchestration
│   │   └── game_analysis_pipeline.py  # 10-step coordinator
│   └── utils/                         # Module utilities
│       ├── validation.py              # Input validation
│       └── correlation.py             # Request tracking
├── scripts/                           # CLI tools
│   └── analyze_game_cli.py           # Command-line interface
├── functions/                         # Cloud deployment
│   ├── main.py                       # HTTP entry point
│   ├── deploy.sh                     # Deployment script
│   └── requirements.txt              # Production deps
└── test_requests/                    # Test data
```

## The 10-Step Pipeline

### Step 0: Dynamic Play Fetching

**Purpose**: Automatically fetch play-by-play data when plays array is empty

**When**: Only when `package.plays` is empty  
**Performance**: ~2 seconds for complete game  
**Benefits**: 90% smaller requests (< 1 KB vs 50-100 KB)

```python
def _fetch_plays_if_needed(self, package: GamePackage) -> GamePackage:
    if package.needs_play_fetching():
        self.logger.info("Step 0: Fetching plays from database...")
        plays = self.play_fetcher.fetch_plays(
            game_id=package.game_id,
            season=package.season,
            week=package.week
        )
        package.plays = plays
    return package
```

**Error Handling**: Returns error if game not found

### Step 1: Validation

**Purpose**: Verify input data completeness and correctness

**Checks**:
- Required fields present (game_id, season, week, plays)
- Field formats valid (game_id pattern, season range)
- Data types correct
- Plays array not empty (after Step 0)

**Output**: Validation warnings for missing optional fields

```python
validation_result = self.validator.validate_package(package)
if not validation_result.passed:
    raise ValidationError(validation_result.errors)
```

### Step 2: Player Extraction

**Purpose**: Identify all unique players who participated in the game

**Process**:
- Scans all plays for player IDs
- Checks multiple fields: passer, rusher, receiver, tackler, etc.
- Deduplicates player IDs
- Typical output: 35-50 unique players

```python
player_ids = self.player_extractor.extract_players(plays)
# Example: {'00-0039732', '00-0038783', ...}
```

### Step 3: Relevance Scoring

**Purpose**: Identify the most impactful players (top 10-25)

**Scoring Criteria**:
- Offensive touches (carries, targets, receptions)
- Yards gained (rushing, receiving)
- Touchdowns scored
- Key plays (3rd down conversions, big gains)
- Defensive impact (tackles, sacks, interceptions)

**Output**: Ranked list of player IDs with relevance scores

```python
selected_players = self.relevance_scorer.score_and_select(
    players=player_ids,
    plays=plays,
    max_players=25
)
```

### Step 4-7: Data Fetching & Normalization

**Skipped in fetch_data=false mode** (production default)

These steps fetch and normalize additional data from external sources when `fetch_data=true`:
- Step 4: Build data requests for NGS stats
- Step 5: Fetch data from providers
- Step 6: Normalize fetched data
- Step 7: Merge with play data

### Step 8: Game Summarization

**Purpose**: Calculate comprehensive team and player statistics

**Team Statistics**:
- Total plays, yards, touchdowns, points
- Passing vs rushing breakdown
- Efficiency metrics (yards/play, completion %)
- Possession time
- Turnovers and penalties

**Player Statistics** (position-specific):
- **QB**: Attempts, completions, yards, TDs, INTs, passer rating
- **RB**: Carries, yards, TDs, yards/carry, receptions
- **WR/TE**: Targets, receptions, yards, TDs, yards/catch
- **DEF**: Tackles, sacks, INTs, forced fumbles

```python
game_summaries = self.game_summarizer.summarize(
    plays=plays,
    selected_players=selected_players
)
```

**NaN Handling**: Skips NaN values in calculations to prevent propagation

### Step 8.5: Player Metadata Enrichment (NEW!)

**Purpose**: Enrich player summaries with names, positions, and teams

**Data Source**: nflreadpy rosters (season-based)  
**Performance**: ~1 second (with caching)  
**Coverage**: Typically 100% of players (25/25)

```python
# Fetch metadata using nflreadpy
player_metadata = self.player_metadata_enricher.fetch_player_metadata(
    player_ids=set(game_summaries.player_summaries.keys()),
    season=package.season
)

# Enrich summaries in-place
self.player_metadata_enricher.enrich_player_summaries(
    player_summaries=game_summaries.player_summaries,
    metadata=player_metadata
)
```

**Implementation Details**:
```python
import nflreadpy as nfl

# Fetch roster data (cached per season)
roster_df = nfl.load_rosters([season])  # Returns Polars DataFrame

# Filter to requested players (using gsis_id column)
player_roster = roster_df.filter(
    roster_df['gsis_id'].is_in(player_ids)
)

# Extract metadata
for row_dict in player_roster.iter_rows(named=True):
    metadata[player_id] = PlayerMetadata(
        player_id=row_dict['gsis_id'],
        name=row_dict['full_name'],      # "Bo Nix"
        position=row_dict['position'],    # "QB"
        team=row_dict['team']            # "DEN"
    )
```

**Benefits**:
- ✅ Zero database coupling (no Supabase dependency)
- ✅ No secrets management required
- ✅ Self-contained function
- ✅ Uses standard nflreadpy package
- ✅ Season-based caching for performance

**Error Handling**: Graceful degradation if enrichment fails (metadata is optional)

### Step 9: Analysis Envelope Creation

**Purpose**: Create compact, LLM-optimized summary (2-5 KB)

**Contents**:
- Game header (teams, date, location)
- Team one-liners (key stats in single string)
- Player quick refs (name, position, key stats)
- Key moments (important play sequences)
- Data links (pointers to full data)

```python
envelope = self.envelope_builder.build_envelope(
    game_info=package,
    summaries=game_summaries,
    plays=plays
)
```

**Design Goal**: Minimal token consumption for AI/LLM analysis

### Step 10: Response Assembly

**Purpose**: Package everything into structured HTTP response

**Response Structure**:
```json
{
  "status": "success",
  "correlation_id": "2025_06_DEN_NYJ-20251015095641-3a2f48a6",
  "game_info": {...},
  "validation": {
    "passed": true,
    "warnings": []
  },
  "processing": {
    "plays_fetched_dynamically": true,
    "players_extracted": 35,
    "players_selected": 25
  },
  "game_summaries": {
    "team_summaries": {...},
    "player_summaries": {...}
  },
  "analysis_envelope": {...},
  "enriched_package": {
    "plays": [...],
    "player_data": [...]
  }
}
```

## Dependencies

### Production Requirements

```txt
# Cloud Function framework
functions-framework==3.*
flask==3.*

# Core processing
python-dotenv>=1.0.0
pandas>=2.0.0
numpy>=1.24.0
polars>=0.19.0              # Required by nflreadpy

# Data sources
nflreadpy>=0.1.0            # Play fetching & player metadata
pytz>=2023.3
pyarrow>=10.0.0
requests>=2.31.0
beautifulsoup4>=4.12.0

# Type checking
typing-extensions>=4.5.0
```

**Key Changes** (October 2025):
- ✅ Using `nflreadpy` (not `nfl-data-py`)
- ✅ Added `polars>=0.19.0` for Polars DataFrame support
- ❌ Removed `supabase>=2.0.0` (no database coupling)

### Import Patterns

```python
# Within module (relative imports)
from ..fetching.play_fetcher import PlayFetcher
from ..processing.game_summarizer import GameSummarizer

# Shared utilities (absolute imports)
from src.shared.utils.logging import setup_logging
from src.shared.db import get_supabase_client

# External packages
import nflreadpy as nfl  # Player metadata enrichment
import polars as pl      # DataFrame operations
```

## Data Contracts

### Input: GamePackage

```python
@dataclass
class GamePackage:
    season: int                    # e.g., 2025
    week: int                      # 1-18 (regular season)
    game_id: str                   # Format: "YYYY_WW_AWAY_HOME"
    plays: List[PlayData]          # Empty array = auto-fetch
    
    def needs_play_fetching(self) -> bool:
        """Check if plays need to be fetched dynamically."""
        return len(self.plays) == 0
```

### Play Data Structure

```python
@dataclass
class PlayData:
    play_id: str
    game_id: str
    posteam: str                   # Possession team
    defteam: str                   # Defense team
    quarter: Optional[float]       # 1-4
    time: Optional[str]            # "14:54"
    down: Optional[int]            # 1-4
    yards_to_go: Optional[int]     # 1-99
    yardline: Optional[int]        # 0-100
    play_type: str                 # "pass", "run", etc.
    yards_gained: Optional[float]
    touchdown: bool
    # Player IDs
    passer_player_id: Optional[str]
    rusher_player_id: Optional[str]
    receiver_player_id: Optional[str]
    # ... more fields
```

**Field Mappings** (from nflreadpy):
- `quarter` ← `qtr` column
- `time` ← `time` column (kept as-is)
- `yards_to_go` ← `ydstogo` column
- `yardline` ← `yardline_100` column

### Player Metadata

```python
@dataclass
class PlayerMetadata:
    player_id: str           # GSIS ID (e.g., "00-0039732")
    name: str                # Full name (e.g., "Bo Nix")
    position: str            # Position (e.g., "QB")
    team: str                # Team abbreviation (e.g., "DEN")
```

**Source**: nflreadpy `load_rosters()` function
- Column: `gsis_id` → `player_id`
- Column: `full_name` → `name`
- Column: `position` → `position`
- Column: `team` → `team`

### Output: Analysis Envelope

```python
@dataclass
class AnalysisEnvelope:
    game: GameHeader              # Basic game info
    teams: List[TeamOneLiner]     # Team summaries
    players: Dict[str, PlayerQuickRef]  # Player quick refs
    key_moments: List[KeyMoment]  # Important sequences
    data_links: Dict[str, DataLink]  # Pointers to full data
```

## API Endpoints

### POST /

**Purpose**: Analyze a complete NFL game

**Request Format**:
```json
{
  "schema_version": "1.0.0",
  "producer": "your-app@1.0.0",
  "fetch_data": false,
  "enable_envelope": true,
  "game_package": {
    "season": 2025,
    "week": 6,
    "game_id": "2025_06_DEN_NYJ",
    "plays": []  // Empty = auto-fetch
  }
}
```

**Response Format**: See Step 10 response structure above

**HTTP Status Codes**:
- `200`: Success
- `400`: Bad request (invalid JSON)
- `422`: Validation failed
- `500`: Internal server error

**Performance**:
- With auto-fetch: ~3-4 seconds
- Without auto-fetch: ~1-2 seconds

## Deployment

### Prerequisites

- Google Cloud project with Cloud Functions enabled
- `gcloud` CLI installed and authenticated
- Permissions: `cloudfunctions.functions.create` and related

### Deploy Command

```bash
cd src/functions/game_analysis_package/functions
./deploy.sh
```

**Deploy Script Features**:
- Automatic source packaging (includes `src/` tree)
- Environment variable configuration
- No secrets required (self-contained)
- Revision tracking
- Health check validation

**Configuration**:
```bash
FUNCTION_NAME="game-analysis"
REGION="us-central1"
RUNTIME="python311"
MEMORY="512MB"
TIMEOUT="60s"
```

**Deployment Output**:
```
Function URL: https://game-analysis-hjm4dt4a5q-uc.a.run.app
Revision: game-analysis-00021-duk
```

### Local Development

**Run local server**:
```bash
cd src/functions/game_analysis_package/functions
./run_local.sh
```

**Test locally**:
```bash
curl -X POST http://localhost:8080 \
  -H 'Content-Type: application/json' \
  -d @../test_requests/http_api_test_minimal.json
```

## Testing

### CLI Tool

```bash
cd src/functions/game_analysis_package
python scripts/analyze_game_cli.py \
  --request test_requests/http_api_test_minimal.json \
  --fetch-plays \
  --pretty
```

**CLI Options**:
- `--request FILE`: Path to JSON request file
- `--fetch-plays`: Enable dynamic play fetching
- `--pretty`: Pretty-print JSON output
- `--output FILE`: Write output to file
- `--verbose`: Enable debug logging

### Test Request Structure

```json
{
  "schema_version": "1.0.0",
  "producer": "test-client@1.0.0",
  "fetch_data": false,
  "enable_envelope": true,
  "game_package": {
    "season": 2025,
    "week": 6,
    "game_id": "2025_06_DEN_NYJ",
    "plays": []
  }
}
```

### Validation Testing

**Test Cases**:
1. Empty plays array (auto-fetch)
2. Provided plays (skip auto-fetch)
3. Invalid game_id format
4. Missing required fields
5. Invalid field types

## Error Handling

### Graceful Degradation

**Player Metadata Enrichment**:
```python
try:
    metadata = enricher.fetch_player_metadata(player_ids, season)
    enricher.enrich_player_summaries(summaries, metadata)
except Exception as e:
    logger.warning(f"Player enrichment failed: {e}")
    # Continue without metadata (optional feature)
```

**NaN Value Handling**:
```python
yards = play.yards_gained or 0.0
if isinstance(yards, (int, float)) and not math.isnan(yards):
    total_yards += yards
```

### Error Response Format

```json
{
  "error": "Failed to fetch plays: No plays found for game 2024_06_DEN_LAC",
  "correlation_id": "2024_06_DEN_LAC-20251015100020-f8b67dbc"
}
```

## Monitoring & Observability

### Correlation IDs

Every request gets a unique correlation ID:
```
Format: {game_id}-{timestamp}-{uuid}
Example: 2025_06_DEN_NYJ-20251015095641-3a2f48a6
```

**Usage**:
- Track requests across pipeline steps
- Debug issues with specific games
- Correlate errors with user reports

### Logging

**Log Levels**:
- `INFO`: Normal operations (pipeline steps, counts)
- `WARNING`: Data quality issues (missing fields, failed enrichment)
- `ERROR`: Processing failures (fetch errors, validation errors)
- `DEBUG`: Detailed diagnostics (field values, intermediate results)

**Enable Debug Logging**:
```bash
export LOG_LEVEL=DEBUG
```

**Example Log Output**:
```
[INFO] Step 0: Fetching plays from database...
[INFO] PlayFetcher: Fetched 164 plays for 2025_06_DEN_NYJ
[INFO] Step 2: Extracting players...
[INFO] Extracted 35 unique players from 164 plays
[INFO] Step 3: Scoring player relevance...
[INFO] Selected 25 players (avg score: 15.35)
[INFO] Step 8: Computing summaries...
[INFO] Computed summaries for 25 players
[INFO] Step 8.5: Enriching player metadata...
[INFO] ✓ Fetched metadata for all 25 players
```

### Cloud Function Logs

**View logs**:
```bash
gcloud functions logs read game-analysis \
  --region=us-central1 \
  --gen2 \
  --limit=100
```

**Filter by correlation ID**:
```bash
gcloud functions logs read game-analysis \
  --region=us-central1 \
  --gen2 \
  --filter="2025_06_DEN_NYJ-20251015095641"
```

## Performance Optimization

### Caching Strategy

**Player Metadata** (season-based):
```python
class PlayerMetadataEnricher:
    def __init__(self):
        self._roster_cache = {}  # Cache by season
    
    def fetch_player_metadata(self, player_ids, season):
        if season not in self._roster_cache:
            roster_df = nfl.load_rosters([season])
            self._roster_cache[season] = roster_df
        else:
            roster_df = self._roster_cache[season]
```

**Benefits**:
- Avoids redundant nflreadpy API calls
- Reduces enrichment time from ~2s to ~0.1s
- Cache persists across function invocations (warm starts)

### Request Size Optimization

**Before** (Advanced Mode):
```json
{
  "game_package": {
    "plays": [/* 164 plays */]
  }
}
// Size: ~80 KB
```

**After** (Simple Mode):
```json
{
  "game_package": {
    "plays": []
  }
}
// Size: < 1 KB (90% reduction!)
```

### Response Size Optimization

**Options**:
1. `enable_envelope: false` → Skip envelope (saves ~2 KB)
2. `fetch_data: false` → Skip external data fetching (default)
3. Filter player data to only selected players

## Security

### No Credentials Required

**Architecture Decision**: Use only public APIs (nflreadpy)
- ✅ No Supabase credentials needed
- ✅ No Google Secret Manager integration
- ✅ No environment variables to protect
- ✅ Simpler deployment

**Deploy Command**:
```bash
gcloud functions deploy game-analysis \
  --clear-env-vars \
  --clear-secrets
```

### Input Validation

**All inputs validated**:
- JSON schema validation
- Field type checking
- Range validation (season, week)
- Format validation (game_id pattern)
- SQL injection prevention (parameterized queries)

## Troubleshooting

### Issue: Player Metadata Not Enriching

**Symptoms**: All players show `player_name: null`

**Root Causes**:
1. Wrong package import (`nfl-data-py` vs `nflreadpy`)
2. Wrong function name (`import_seasonal_rosters` vs `load_rosters`)
3. Wrong column names (`player_id` vs `gsis_id`)
4. Wrong DataFrame type (pandas vs Polars)

**Solution** (Implemented in rev 00021):
```python
import nflreadpy as nfl  # Correct package

roster_df = nfl.load_rosters([season])  # Correct function

# Correct column names (Polars DataFrame)
player_roster = roster_df.filter(
    roster_df['gsis_id'].is_in(player_ids)  # Correct column
)

for row_dict in player_roster.iter_rows(named=True):  # Polars iteration
    metadata[player_id] = PlayerMetadata(
        player_id=row_dict['gsis_id'],
        name=row_dict['full_name'],  # Correct column
        position=row_dict['position'],
        team=row_dict['team']
    )
```

### Issue: NaN Values in Calculations

**Symptoms**: `total_yards: NaN`, `yards_per_play: NaN`

**Root Cause**: Some plays have NaN yards_gained, NaN propagates in sum

**Solution**:
```python
import math

yards = play.yards_gained or 0.0
if isinstance(yards, (int, float)) and not math.isnan(yards):
    total_yards += yards  # Only add non-NaN values
```

### Issue: Missing Play Fields

**Symptoms**: `quarter: null`, `time: null`, `yards_to_go: null`

**Root Cause**: Field name mismatches in transformer

**Solution**: Update PlayByPlayDataTransformer mapping:
```python
"quarter": record.get("qtr") or record.get("quarter"),
"time": record.get("time"),  # Not "clock"
"yards_to_go": record.get("ydstogo"),  # Not "distance"
"yardline": record.get("yardline_100")  # Not just "yardline"
```

### Issue: Play Fetching Fails

**Symptoms**: `Failed to fetch plays: No plays found for game`

**Causes**:
1. Game doesn't exist in database
2. Wrong game_id format
3. Database connection issue

**Debug**:
```bash
# Check Cloud Function logs
gcloud functions logs read game-analysis --limit=50

# Verify game exists
SELECT COUNT(*) FROM plays WHERE game_id = '2025_06_DEN_NYJ';
```

## Development Guidelines

### Adding New Features

1. **Determine scope**: Module-specific or shared?
2. **Module-specific** → Add to `core/`
3. **Truly generic** → Add to `src/shared/`
4. Update pipeline if needed (add new step)
5. Update contracts if data structure changes
6. Add tests
7. Update documentation

### Code Style

- Follow PEP 8 with 4-space indentation
- Use type hints for all function signatures
- Docstrings for all public methods
- Relative imports within module
- Absolute imports for shared code

### Testing Strategy

1. **Unit tests**: Test individual components
2. **Integration tests**: Test pipeline steps
3. **End-to-end tests**: Test complete API flow
4. **Performance tests**: Measure response times
5. **Load tests**: Test under concurrent load

## Recent Changes

### October 2025 - Player Metadata Enrichment

**Changes**:
- Added `PlayerMetadataEnricher` class
- Integrated nflreadpy for player metadata
- Added Step 8.5 to pipeline
- Fixed field mappings (gsis_id, full_name)
- Added Polars DataFrame support
- Removed database dependency for metadata
- Removed secrets management

**Revision**: 00021-duk

**Benefits**:
- ✅ 100% player coverage (25/25 enriched)
- ✅ Zero database coupling
- ✅ No secrets required
- ✅ Simpler architecture
- ✅ Better maintainability

### October 2025 - Dynamic Play Fetching

**Changes**:
- Added `PlayFetcher` class
- Added Step 0 to pipeline
- Support for empty plays array
- 90% request size reduction

**Revision**: 00019-ces

**Benefits**:
- ✅ Minimal request payloads
- ✅ No client-side data prep
- ✅ Always current database data
- ✅ Backward compatible

### September 2025 - Initial Release

**Features**:
- 9-step pipeline
- Team and player summarization
- Analysis envelope creation
- Cloud Function deployment

**Revision**: 00001-xxx

## References

### Documentation
- **Integration Guide**: For non-technical users
- **Deployment Guide**: Cloud Function deployment
- **Module README**: Quick start and usage

### Code Locations
- Pipeline: `src/functions/game_analysis_package/core/pipeline/`
- Contracts: `src/functions/game_analysis_package/core/contracts/`
- Enrichment: `src/functions/game_analysis_package/core/fetching/`

### External Resources
- [nflreadpy Documentation](https://github.com/dynastyprocess/nflreadpy)
- [Polars Documentation](https://pola-rs.github.io/polars/)
- [Google Cloud Functions](https://cloud.google.com/functions)

## Support

### Getting Help
1. Check validation warnings in responses
2. Review error messages for guidance
3. Check Cloud Function logs with correlation ID
4. Contact development team with details

### Reporting Issues
Include:
- Correlation ID
- Request payload (sanitized)
- Error message
- Expected vs actual behavior
- Environment details

---

**Last Updated**: October 15, 2025  
**Version**: 1.0.0  
**Maintainer**: Development Team
