# Design Document

## Overview

The Game Analysis Package feature creates a new independent module `game_analysis_package` that transforms raw play-by-play game data into enriched, LLM-ready analysis packages. The module follows the established function-based isolation architecture, integrating with existing data loading capabilities while maintaining complete independence.

The system processes game packages through a 9-step pipeline: validation, player extraction, relevance scoring, data request bundling, upstream fetching, normalization, summarization, envelope creation, and response formatting. It produces both comprehensive enriched packages and compact analysis envelopes optimized for AI consumption.

## Architecture

### Module Structure
Following the established pattern from existing modules:

```
src/functions/game_analysis_package/
├── core/                           # Business logic
│   ├── contracts/                  # Data contracts and types
│   │   ├── __init__.py
│   │   ├── game_package.py         # Input game package contract
│   │   ├── analysis_envelope.py    # LLM-ready output contract
│   │   └── enriched_package.py     # Full enriched package contract
│   ├── extraction/                 # Player extraction and relevance
│   │   ├── __init__.py
│   │   ├── player_extractor.py     # Extract players from plays
│   │   └── relevance_scorer.py     # Score player relevance
│   ├── bundling/                   # Data request management
│   │   ├── __init__.py
│   │   ├── request_builder.py      # Build combined data requests
│   │   └── data_fetcher.py         # Fetch from upstream sources
│   ├── processing/                 # Data processing and normalization
│   │   ├── __init__.py
│   │   ├── normalizer.py           # Clean and normalize data
│   │   ├── summarizer.py           # Compute team/player summaries
│   │   └── envelope_builder.py     # Create LLM-friendly envelopes
│   ├── pipelines/                  # Main orchestration
│   │   ├── __init__.py
│   │   └── analysis_pipeline.py    # Main 9-step pipeline
│   └── utils/                      # Module utilities
│       ├── __init__.py
│       ├── validation.py           # Input validation
│       └── correlation.py          # Correlation ID management
├── scripts/                        # CLI tools
│   ├── __init__.py
│   ├── _bootstrap.py              # Environment setup
│   └── analyze_game_cli.py        # CLI entry point
├── functions/                      # Cloud Function deployment
│   ├── main.py                    # HTTP entry point (analysis_handler)
│   ├── deploy.sh                  # Deployment script
│   ├── run_local.sh              # Local testing script
│   └── requirements.txt           # Function dependencies
├── requirements.txt               # Module dependencies
├── .env.example                   # Configuration template
└── README.md                      # Module documentation
```

### Integration Points

**Data Loading Integration:**
- Leverages existing package contract from `src/functions/data_loading/core/contracts/package.py`
- Uses existing providers via `src/functions/data_loading/core/providers/registry.py`
- Follows established request/response patterns from `docs/package_contract.md`

**Shared Utilities:**
- Database connections via `src/shared/db/connection.py`
- Logging via `src/shared/utils/logging.py`
- Environment configuration via `src/shared/utils/env.py`

**Independence:**
- No direct imports from other function modules
- Self-contained business logic in `core/`
- Independent deployment and testing

**HTTP API Exposure:**
- Cloud Function endpoint: `https://<region>-<project>.cloudfunctions.net/game-analysis`
- Follows same CORS and error handling patterns as data loading API
- Accepts POST requests with game package JSON payloads
- Returns both enriched packages and analysis envelopes

## Components and Interfaces

### Core Pipeline (analysis_pipeline.py)

```python
class GameAnalysisPipeline:
    """Main orchestration pipeline implementing the 9-step process."""
    
    def process_game_package(self, game_package: GamePackageInput) -> GameAnalysisResult:
        """Execute the complete 9-step analysis pipeline."""
        
        # Step 1: Validate input package
        validated_package = self.validator.validate_package(game_package)
        
        # Step 2: Extract player IDs from plays
        player_ids = self.player_extractor.extract_players(validated_package.plays)
        
        # Step 3: Score player relevance
        relevant_players = self.relevance_scorer.score_and_select(
            player_ids, validated_package.plays
        )
        
        # Step 4: Build combined data request
        data_request = self.request_builder.build_request(
            game_info=validated_package.game_info,
            relevant_players=relevant_players
        )
        
        # Step 5: Fetch and merge data
        merged_data = self.data_fetcher.fetch_and_merge(data_request)
        
        # Step 6: Clean and normalize
        normalized_data = self.normalizer.normalize(merged_data)
        
        # Step 7: Compute summaries
        summaries = self.summarizer.compute_summaries(normalized_data)
        
        # Step 8: Create analysis envelope
        envelope = self.envelope_builder.create_envelope(
            normalized_data, summaries
        )
        
        # Step 9: Return enriched package and envelope
        return GameAnalysisResult(
            enriched_package=normalized_data,
            analysis_envelope=envelope,
            correlation_id=validated_package.correlation_id
        )
```

### Player Extraction (player_extractor.py)

```python
class PlayerExtractor:
    """Extracts all unique player IDs from play-by-play data."""
    
    def extract_players(self, plays: List[PlayData]) -> Set[str]:
        """Scan all plays and collect unique player IDs."""
        
        player_ids = set()
        for play in plays:
            # Extract from all play action fields
            player_ids.update(self._extract_from_play(play))
        
        return player_ids
    
    def _extract_from_play(self, play: PlayData) -> Set[str]:
        """Extract player IDs from a single play."""
        # Check rusher, receiver, passer, returner, tackler, etc.
        # Handle both individual IDs and lists of IDs
```

### Relevance Scoring (relevance_scorer.py)

```python
class RelevanceScorer:
    """Computes player relevance scores and selects balanced sets."""
    
    def score_and_select(self, player_ids: Set[str], plays: List[PlayData]) -> List[RelevantPlayer]:
        """Score players and return balanced selection."""
        
        # Compute impact signals for each player
        player_scores = {}
        for player_id in player_ids:
            signals = self._compute_impact_signals(player_id, plays)
            player_scores[player_id] = self._calculate_relevance_score(signals)
        
        # Select balanced set (top 5 per team, all significant QBs, scorers)
        return self._select_balanced_set(player_scores, plays)
    
    def _compute_impact_signals(self, player_id: str, plays: List[PlayData]) -> ImpactSignals:
        """Compute frequency, production, and high-leverage metrics."""
        
    def _calculate_relevance_score(self, signals: ImpactSignals) -> float:
        """Combine signals into single relevance score."""
        
    def _select_balanced_set(self, scores: Dict[str, float], plays: List[PlayData]) -> List[RelevantPlayer]:
        """Apply selection rules for balanced player set."""
```

### Request Building (request_builder.py)

```python
class DataRequestBuilder:
    """Builds combined data requests for upstream sources."""
    
    def build_request(self, game_info: GameInfo, relevant_players: List[RelevantPlayer]) -> CombinedDataRequest:
        """Create single request for all required data sources."""
        
        return CombinedDataRequest(
            play_by_play=self._build_pbp_request(game_info),
            snap_counts=self._build_snap_counts_request(game_info),
            team_context=self._build_team_context_request(game_info),
            player_ngs=self._build_ngs_requests(relevant_players, game_info)
        )
    
    def _build_ngs_requests(self, players: List[RelevantPlayer], game_info: GameInfo) -> List[NGSRequest]:
        """Build position-appropriate NGS requests."""
        # QB → passing, WR/TE → receiving, RB → rushing
        # Add secondary stat types when warranted
```

### Data Fetching (data_fetcher.py)

```python
class DataFetcher:
    """Fetches data from upstream sources using existing providers."""
    
    def __init__(self):
        # Use existing data loading providers
        from src.functions.data_loading.core.providers.registry import get_provider
        self.get_provider = get_provider
    
    def fetch_and_merge(self, request: CombinedDataRequest) -> MergedGameData:
        """Fetch all data sources and merge into coherent structure."""
        
        # Fetch each data source
        pbp_data = self._fetch_play_by_play(request.play_by_play)
        snap_data = self._fetch_snap_counts(request.snap_counts)
        team_data = self._fetch_team_context(request.team_context)
        ngs_data = self._fetch_ngs_data(request.player_ngs)
        
        # Merge into coherent structure keyed by game/teams/players
        return self._merge_data_sources(pbp_data, snap_data, team_data, ngs_data)
```

### Data Processing (normalizer.py, summarizer.py)

```python
class DataNormalizer:
    """Cleans and normalizes merged data."""
    
    def normalize(self, merged_data: MergedGameData) -> NormalizedGameData:
        """Replace invalid values, ensure consistent identifiers."""
        
        # Replace "NaN" with null, standardize IDs, add provenance
        
class GameSummarizer:
    """Computes team and player summaries."""
    
    def compute_summaries(self, data: NormalizedGameData) -> GameSummaries:
        """Calculate team and player performance metrics."""
        
        team_summaries = self._compute_team_summaries(data)
        player_summaries = self._compute_player_summaries(data)
        
        return GameSummaries(teams=team_summaries, players=player_summaries)
```

### HTTP Function (functions/main.py)

```python
def analysis_handler(request):
    """HTTP Cloud Function entry point for game analysis."""
    
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        return ('', 204, cors_headers)
    
    if request.method != 'POST':
        return ({'error': 'Method not allowed'}, 405, cors_headers)
    
    try:
        # Parse request JSON
        request_data = request.get_json()
        if not request_data:
            return ({'error': 'Invalid JSON body'}, 400, cors_headers)
        
        # Extract game package
        game_package = request_data.get('game_package')
        if not game_package:
            return ({'error': 'Missing game_package field'}, 400, cors_headers)
        
        # Process through pipeline
        pipeline = GameAnalysisPipeline()
        result = pipeline.process_game_package(GamePackageInput(**game_package))
        
        # Return structured response
        response = {
            'schema_version': '1.0.0',
            'correlation_id': result.correlation_id,
            'enriched_package': result.enriched_package.to_dict(),
            'analysis_envelope': result.analysis_envelope.to_dict()
        }
        
        return (response, 200, cors_headers)
        
    except ValidationError as e:
        return ({'error': f'Validation failed: {str(e)}'}, 422, cors_headers)
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return ({'error': 'Internal server error'}, 500, cors_headers)
```

### Envelope Creation (envelope_builder.py)

```python
class AnalysisEnvelopeBuilder:
    """Creates compact, LLM-friendly analysis envelopes."""
    
    def create_envelope(self, data: NormalizedGameData, summaries: GameSummaries) -> AnalysisEnvelope:
        """Build compact envelope optimized for AI consumption."""
        
        return AnalysisEnvelope(
            game_header=self._create_game_header(data.game_info),
            team_summaries=self._create_team_summaries(summaries.teams),
            player_map=self._create_player_map(summaries.players),
            key_sequences=self._extract_key_sequences(data.plays),
            data_pointers=self._create_data_pointers(data)
        )
    
    def _extract_key_sequences(self, plays: List[PlayData]) -> List[KeySequence]:
        """Identify and label notable game moments."""
        # Scoring plays, turnovers, explosive plays, etc.
```

## Data Models

### Input Contracts

```python
@dataclass
class GamePackageInput:
    """Input game package structure."""
    season: int
    week: int
    game_id: str
    plays: List[PlayData]
    correlation_id: Optional[str] = None

@dataclass
class PlayData:
    """Individual play data structure."""
    play_id: str
    game_id: str
    # All play-by-play fields (rusher, receiver, etc.)
```

### Processing Models

```python
@dataclass
class RelevantPlayer:
    """Player selected for analysis."""
    player_id: str
    name: str
    position: str
    team: str
    relevance_score: float
    impact_signals: ImpactSignals

@dataclass
class ImpactSignals:
    """Player impact metrics."""
    play_frequency: int
    touches: int
    yards: float
    touchdowns: int
    high_leverage_events: List[str]
```

### Output Contracts

```python
@dataclass
class AnalysisEnvelope:
    """Compact, LLM-ready analysis package."""
    game_header: GameHeader
    team_summaries: Dict[str, TeamSummary]
    player_map: Dict[str, PlayerSummary]
    key_sequences: List[KeySequence]
    data_pointers: Dict[str, str]

@dataclass
class GameAnalysisResult:
    """Complete analysis result."""
    enriched_package: NormalizedGameData
    analysis_envelope: AnalysisEnvelope
    correlation_id: str
```

## Error Handling

### Validation Errors
- **Invalid Package Structure**: Return descriptive error with game ID and specific issues
- **Missing Required Fields**: Identify missing fields and provide correction guidance
- **Malformed Game ID**: Validate format and provide examples

### Data Fetching Errors
- **Upstream Source Failures**: Graceful degradation with partial data
- **Rate Limiting**: Implement retry logic with exponential backoff
- **Data Quality Issues**: Log warnings but continue processing

### Processing Errors
- **Player Extraction Failures**: Log issues but continue with available players
- **Relevance Scoring Errors**: Use fallback scoring methods
- **Normalization Issues**: Apply best-effort cleaning with warnings

## Testing Strategy

### Unit Testing
- **Player Extraction**: Test with various play-by-play formats
- **Relevance Scoring**: Verify scoring algorithms and selection logic
- **Data Normalization**: Test edge cases (NaN values, missing fields)
- **Envelope Creation**: Validate LLM-friendly format requirements

### Integration Testing
- **End-to-End Pipeline**: Test complete 9-step process with real game data
- **Provider Integration**: Verify compatibility with existing data loading providers
- **Error Scenarios**: Test graceful handling of upstream failures

### Performance Testing
- **Large Game Processing**: Test with games having many plays and players
- **Memory Usage**: Monitor memory consumption during processing
- **Response Times**: Ensure acceptable latency for API consumers

### Manual Testing
- **CLI Tool**: Test command-line interface with various game packages
- **HTTP API**: Test Cloud Function deployment and CORS handling using curl
- **Local Testing**: Use `run_local.sh` for development testing
- **Data Quality**: Manual review of analysis envelopes for accuracy

### API Testing Examples

**Local Testing**:
```bash
cd src/functions/game_analysis_package/functions
./run_local.sh

# Test with curl
curl -X POST http://localhost:8080 \
  -H "Content-Type: application/json" \
  -d @../test_requests/sample_game_package.json
```

**Production Testing**:
```bash
curl -X POST https://us-central1-project.cloudfunctions.net/game-analysis \
  -H "Content-Type: application/json" \
  -d @test_requests/sample_game_package.json
```

## Implementation Notes

### Dependency Management
- Use existing data loading providers without modification
- Leverage shared utilities for database, logging, and environment
- Maintain independent `requirements.txt` for module-specific dependencies

### Configuration
- Follow existing pattern with `.env.example` and central `.env` file
- Use same Supabase configuration as other modules
- Add module-specific configuration variables as needed

### HTTP API Design

**Endpoint**: `POST /` (Cloud Function entry point)

**Request Format**:
```json
{
  "schema_version": "1.0.0",
  "producer": "client.system/analysis@1.0.0",
  "game_package": {
    "season": 2024,
    "week": 5,
    "game_id": "2024_05_SF_KC",
    "plays": [...],
    "correlation_id": "optional-trace-id"
  }
}
```

**Response Format**:
```json
{
  "schema_version": "1.0.0",
  "correlation_id": "game-2024_05_SF_KC-abc123",
  "enriched_package": {
    "game_info": {...},
    "teams": {...},
    "players": {...},
    "data_sources": {...}
  },
  "analysis_envelope": {
    "game_header": {...},
    "team_summaries": {...},
    "player_map": {...},
    "key_sequences": [...],
    "data_pointers": {...}
  }
}
```

**Error Handling**:
- `400`: Invalid JSON or missing required fields
- `422`: Valid JSON but failed validation (malformed game package)
- `500`: Unexpected processing errors
- `405`: Non-POST methods
- `204`: OPTIONS preflight requests

**CORS Support**: Same permissive headers as data loading API

### Deployment
- Independent Cloud Function deployment following existing patterns
- Use same deployment script structure as other modules
- Support both CLI and HTTP API access patterns
- Function name: `game-analysis` (deployed endpoint)

### Monitoring and Logging
- Use existing logging infrastructure from `src/shared/utils/logging.py`
- Log correlation IDs for request tracing
- Monitor processing times and data quality metrics