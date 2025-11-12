#!/bin/bash
# Test script for validation results display in daily_team_update pipeline

# Navigate to the module root
cd "$(dirname "$0")/.." || exit 1

echo "===================================================================="
echo "Testing Validation Results Display Integration"
echo "===================================================================="
echo ""
echo "This test will run the daily_team_update pipeline with validation"
echo "results display enabled to show claims identification and detailed"
echo "validation output in the terminal."
echo ""
echo "Environment Configuration:"
echo "  DISPLAY_VALIDATION_DETAILS=true"
echo ""
echo "===================================================================="
echo ""

# Enable validation display
export DISPLAY_VALIDATION_DETAILS=true

# Run the pipeline for a single team (NYG as example)
# Adjust the command based on your actual CLI setup
python3 scripts/run_pipeline_cli.py --team NYG "$@"

echo ""
echo "===================================================================="
echo "Test Complete"
echo "===================================================================="
echo ""
echo "If you saw formatted validation results above with:"
echo "  - Claims identification (with priority scores and categories)"
echo "  - Factual validation results (with grounding support info)"
echo "  - Contextual validation results"
echo "  - Quality validation results"
echo "  - Any validation issues (color-coded by severity)"
echo ""
echo "Then the integration is working correctly!"
echo ""
echo "To disable the display in production, either:"
echo "  1. Unset DISPLAY_VALIDATION_DETAILS, or"
echo "  2. Set DISPLAY_VALIDATION_DETAILS=false"
echo ""
