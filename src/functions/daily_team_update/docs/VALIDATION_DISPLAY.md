# Validation Results Display

## Overview

The validation results display feature provides detailed, formatted output of article validation results during the daily team update pipeline runs. This helps operators understand the validation process, claims identification, and any issues encountered.

## Features

- **Claims Identification Display**: Shows all claims extracted from articles with:
  - Claim text
  - Priority scores (0.0-1.0)
  - Categories (STATISTIC, EVENT, FACTUAL, etc.)
  - Verification results
  
- **Validation Dimensions**: Displays results for:
  - Factual Validation (with Google Search grounding support)
  - Contextual Validation
  - Quality Validation
  
- **Issue Highlighting**: Color-coded display of validation issues by severity:
  - 🔴 CRITICAL (red)
  - 🟡 WARNING (yellow)
  - 🔵 INFO (blue)

- **Summary Statistics**: Shows overall validation status and metrics

## Usage

### Enable Display

Set the environment variable before running the pipeline:

```bash
export DISPLAY_VALIDATION_DETAILS=true
python3 scripts/run_pipeline_cli.py --team NYG
```

Or inline:

```bash
DISPLAY_VALIDATION_DETAILS=true python3 scripts/run_pipeline_cli.py --team NYG
```

### Disable Display

Unset the variable or set it to false:

```bash
unset DISPLAY_VALIDATION_DETAILS
# or
export DISPLAY_VALIDATION_DETAILS=false
python3 scripts/run_pipeline_cli.py --team NYG
```

### Test Script

A convenience test script is provided:

```bash
cd src/functions/daily_team_update
./scripts/test_validation_display.sh
```

## Implementation Details

### Components

1. **display_validation_results.py**: Core display logic with ANSI color formatting
   - `ValidationResultsDisplay` class
   - Methods for each validation dimension
   - Claims identification formatting
   - Issue display with severity coloring

2. **service_coordinator.py**: Integration point
   - `_should_display_validation_details()`: Checks environment variable
   - `_display_validation_results()`: Calls display module
   - Integration in `validate_article()` method

### Configuration

The display is controlled by the `DISPLAY_VALIDATION_DETAILS` environment variable:

- **Enabled**: `1`, `true`, `yes`, `on` (case-insensitive)
- **Disabled**: Any other value or unset (default)

### Example Output

```
================================================================================
VALIDATION RESULTS - NYG
================================================================================

FACTUAL VALIDATION
────────────────────────────────────────────────────────────────────────────────
Status: ✅ PASS
Score: 0.92/1.00
Support: Google Search Grounding Enabled

Claims Identification:
  ✓ Claim 1 [STATISTIC] Priority: 0.900
    "The Giants scored 24 points in the fourth quarter"
    Verification: VERIFIED with confidence 0.95

  ✓ Claim 2 [EVENT] Priority: 0.780
    "Daniel Jones threw for 300 yards"
    Verification: VERIFIED with confidence 0.88

CONTEXTUAL VALIDATION
────────────────────────────────────────────────────────────────────────────────
Status: ✅ PASS
Score: 0.88/1.00

QUALITY VALIDATION
────────────────────────────────────────────────────────────────────────────────
Status: ✅ PASS
Score: 0.95/1.00

VALIDATION SUMMARY
────────────────────────────────────────────────────────────────────────────────
Overall Status: ✅ PASS
Dimensions: 3/3 passed
Issues: 0
```

## Environment Variables

| Variable | Values | Default | Description |
|----------|--------|---------|-------------|
| `DISPLAY_VALIDATION_DETAILS` | `true`, `false`, `1`, `0`, `yes`, `no`, `on`, `off` | `false` | Enable/disable validation display |

## Notes

- Display only appears when validation service is called
- Display is optional and doesn't affect pipeline execution
- Errors in display are logged at DEBUG level but don't fail the pipeline
- ANSI colors require terminal support (most modern terminals)
- Display is automatically disabled if terminal doesn't support colors

## Troubleshooting

### Display Not Showing

1. Check environment variable:
   ```bash
   echo $DISPLAY_VALIDATION_DETAILS
   ```

2. Verify validation is actually being called in the pipeline

3. Check logs for display errors:
   ```bash
   export LOG_LEVEL=DEBUG
   python3 scripts/run_pipeline_cli.py --team NYG
   ```

### Colors Not Working

Some terminals may not support ANSI colors. The display module attempts to handle this gracefully by falling back to plain text, but if you see garbled output, try:

```bash
export NO_COLOR=1
DISPLAY_VALIDATION_DETAILS=true python3 scripts/run_pipeline_cli.py --team NYG
```

## Future Enhancements

Potential improvements:
- JSON output mode for machine processing
- Configurable verbosity levels
- Export validation results to file
- Integration with logging system for persistent records
