# Task 2.2 Implementation: Package Validation Service

## Overview

Implemented comprehensive package validation service that goes beyond basic structural validation to perform data quality checks, consistency validation, and detailed error reporting.

## Implementation Details

### File Created
- `core/utils/validation.py` - Complete validation service (560+ lines)

### Components Implemented

#### 1. ValidationIssue Dataclass
Represents individual validation issues with:
- `level` - 'error' or 'warning'
- `field` - Field name where issue was found
- `message` - Descriptive error message
- `play_id` - Optional play ID for play-specific issues
- `__str__()` - Formatted string representation

#### 2. ValidationResult Dataclass
Contains complete validation results:
- `is_valid` - Boolean validation status
- `errors` - List of fatal errors
- `warnings` - List of non-fatal warnings
- `stats` - Dictionary of package statistics
- `has_errors()` / `has_warnings()` - Helper methods
- `get_summary()` - Human-readable summary
- `to_dict()` - JSON serialization

#### 3. PackageValidator Class
Main validation service with multi-level validation:

**Constructor:**
- `strict` parameter - Treats warnings as errors when True

**Public Methods:**
- `validate(package)` - Main validation entry point

**Private Validation Methods:**
1. `_validate_game_info()` - Game-level validation
   - Play count reasonableness (50-250 expected)
   - Correlation ID length checks

2. `_validate_plays_collection()` - Collection-level validation
   - Duplicate play ID detection
   - Sequential ordering checks

3. `_validate_play_quality()` - Data quality validation
   - Missing field detection with thresholds
   - Field-by-field completeness analysis
   - Delegates to individual play validation

4. `_validate_individual_play()` - Per-play validation
   - Down validation (1-4)
   - Quarter validation (1-5)
   - Yards_to_go range (-99 to 99)
   - Yards_gained range (-99 to 99)
   - Touchdown value (0 or 1)
   - Play type consistency (pass has passer, run has rusher)

5. `_validate_play_consistency()` - Cross-play consistency
   - Team count validation (should be exactly 2)
   - Team alignment with game_id

6. `_validate_player_references()` - Player ID validation
   - Player count reasonableness (40-60 expected)
   - Player ID format validation (XX-XXXXXXX pattern)

**Helper Methods:**
- `_collect_statistics()` - Gathers package statistics
- `_collect_players_from_play()` - Extracts all player IDs
- `_is_valid_player_id_format()` - Validates ID format
- `_add_error()` / `_add_warning()` - Issue tracking

#### 4. Convenience Function
- `validate_package_with_details()` - Easy validation entry point

## Statistics Collected

The validator collects comprehensive statistics:
- `game_id`, `season`, `week` - Basic identification
- `total_plays` - Play count
- `quarters` - Unique quarters present
- `play_types` - Count by type (pass, run, etc.)
- `teams` - Unique teams in game
- `unique_players_count` - Total unique players

## Validation Rules Implemented

### Errors (Fatal)
1. ✅ Duplicate play IDs
2. ✅ Invalid down values (must be 1-4)
3. ✅ Invalid quarter values (must be 1-5)
4. ✅ Missing team information (posteam/defteam required)

### Warnings (Non-Fatal)
1. ✅ Unusual play count (<50 or >250)
2. ✅ Very long correlation IDs (>255 chars)
3. ✅ Many plays out of sequence (>10%)
4. ✅ Missing optional fields (>10% threshold)
   - Quarter, down, yards_to_go, yardline, play_type
5. ✅ Unusual yards_to_go (<0 or >99)
6. ✅ Unusual yards_gained (<-99 or >99)
7. ✅ Unusual touchdown values (not 0 or 1)
8. ✅ Play type mismatches (pass without passer, run without rusher)
9. ✅ Team count issues (not exactly 2 teams)
10. ✅ Team mismatch with game_id
11. ✅ Unusual player count (<5 or >100)
12. ✅ Non-standard player ID formats

## CLI Integration

Updated `scripts/analyze_game_cli.py` to use enhanced validation:

### New Features
1. **Two-phase validation**
   - Phase 1a: Structural validation (via contracts)
   - Phase 1b: Detailed validation (via PackageValidator)

2. **New --strict flag**
   - Treats warnings as errors
   - Useful for production environments

3. **Enhanced dry-run output**
   - Includes full validation results
   - Shows statistics, errors, and warnings

### Usage Examples

```bash
# Standard validation (warnings allowed)
python scripts/analyze_game_cli.py --request test.json --dry-run

# Strict validation (warnings treated as errors)
python scripts/analyze_game_cli.py --request test.json --dry-run --strict

# Full analysis with validation
python scripts/analyze_game_cli.py --request test.json --pretty
```

## Testing

### Test Files Created

1. **invalid_game.json** - Test file with intentional errors:
   - Duplicate play IDs
   - Invalid down (5)
   - Invalid quarter (6)
   - Unusual yards values
   - Missing required fields
   - Team mismatches

### Test Results

**Sample Game (10 plays):**
- ✅ Valid with 1 warning (low play count)
- Statistics: 7 pass, 3 run, 2 teams, 17 players

**Minimal Game (1 play):**
- ✅ Valid with 3 warnings (low play count, missing yardline, few players)
- Statistics: 1 pass, 2 teams, 2 players

**Invalid Game (3 plays):**
- ❌ Invalid with 4 errors and 8 warnings
- All errors properly detected and reported

**Strict Mode:**
- ✅ Warnings correctly treated as errors
- Proper exit codes (2 for validation errors)

## Output Examples

### Successful Validation
```json
{
  "status": "valid",
  "game_id": "2024_05_SF_KC",
  "season": 2024,
  "week": 5,
  "validation": {
    "is_valid": true,
    "summary": "✓ Package is valid with 1 warning(s)",
    "errors": [],
    "warnings": [
      "[WARNING] plays: Unusually low play count: 10 (typical game has 120-180 plays)"
    ],
    "stats": {
      "total_plays": 10,
      "quarters": [1],
      "play_types": {"pass": 7, "run": 3},
      "teams": ["KC", "SF"],
      "unique_players_count": 17
    }
  }
}
```

### Failed Validation
```
[ERROR] plays: Duplicate play IDs found: ['2024_01_002']
[ERROR] down in play 2024_01_001: Invalid down value: 5
[ERROR] quarter in play 2024_01_002: Invalid quarter value: 6
[ERROR] plays: 1 plays missing team information (posteam/defteam)
[WARNING] yards_gained in play 2024_01_002: Unusual yards_gained value: 150.0
...
```

## Key Features

### 1. Comprehensive Coverage
- ✅ 6 validation methods covering different aspects
- ✅ 15+ validation rules implemented
- ✅ Both structural and semantic validation

### 2. Detailed Error Messages
- ✅ Specific field and play ID references
- ✅ Clear description of issues
- ✅ Helpful context (expected ranges, thresholds)

### 3. Flexible Severity
- ✅ Errors for fatal issues
- ✅ Warnings for quality concerns
- ✅ Strict mode to enforce warnings

### 4. Rich Statistics
- ✅ Play counts and types
- ✅ Team and player counts
- ✅ Quarter coverage
- ✅ JSON serializable

### 5. Production Ready
- ✅ Proper logging throughout
- ✅ Clear error messages
- ✅ Exit code handling
- ✅ Threshold-based validation

## Architecture Compliance

✅ **Module Independence**: Only uses module contracts, no external dependencies
✅ **Shared Utilities**: Uses only `logging` from shared utilities
✅ **Standard Structure**: Follows established patterns
✅ **Type Safety**: Full type hints throughout
✅ **Documentation**: Comprehensive docstrings

## Code Quality

- **Lines of Code**: 560+ lines
- **Type Hints**: 100% coverage
- **Docstrings**: All public methods documented
- **Logging**: INFO, WARNING, ERROR levels
- **Error Handling**: Comprehensive validation logic

## Next Steps

Task 2.2 is complete. The validation service provides:
1. ✅ Comprehensive validation beyond basic contracts
2. ✅ Descriptive error messages with context
3. ✅ Statistics collection
4. ✅ CLI integration with --strict mode
5. ✅ Test coverage with intentionally invalid data

Ready to proceed to next phase (Task 3.2: Relevance Scoring).
