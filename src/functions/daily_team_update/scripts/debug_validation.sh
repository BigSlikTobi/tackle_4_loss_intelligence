#!/bin/bash
# Debug script to investigate empty validation responses

cd "$(dirname "$0")/.." || exit 1

echo "===================================================================="
echo "Debugging Validation Empty Responses"
echo "===================================================================="
echo ""
echo "Running with DEBUG logging to capture finish_reason and LLM details"
echo ""

# Enable DEBUG logging and validation display
export LOG_LEVEL=DEBUG
export DISPLAY_VALIDATION_DETAILS=true

# Run for a single team
python3 scripts/run_pipeline_cli.py --team NYG "$@" 2>&1 | tee validation_debug.log

echo ""
echo "===================================================================="
echo "Log saved to validation_debug.log"
echo "===================================================================="
echo ""
echo "Key things to look for:"
echo "  - 'Finish reason:' entries (shows why model stopped generating)"
echo "  - 'Empty response' messages"
echo "  - 'Web search queries:' (shows if grounding was used)"
echo "  - 'Grounding sources:' (shows if grounding provided results)"
echo ""
echo "Common finish_reasons:"
echo "  - STOP: Normal completion"
echo "  - MAX_TOKENS: Response too long"
echo "  - SAFETY: Content filtered by safety settings"
echo "  - RECITATION: Content blocked due to recitation"
echo "  - OTHER: Unknown reason"
echo ""
