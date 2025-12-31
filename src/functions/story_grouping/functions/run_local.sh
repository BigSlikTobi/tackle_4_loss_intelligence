#!/bin/bash
# Script to run the story grouping function locally for testing

set -e

# Configuration
FUNCTION_TARGET="group_stories"
PORT=8080

# Paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${YELLOW}Starting $FUNCTION_TARGET locally on port $PORT...${NC}"

# Check for .env file
ENV_FILE="$PROJECT_ROOT/.env"
if [ -f "$ENV_FILE" ]; then
    echo "Loading environment variables from $ENV_FILE"
    # Export variables from .env
    set -a
    source "$ENV_FILE"
    set +a
else
    echo -e "${RED}Error: .env file not found at $ENV_FILE${NC}"
    exit 1
fi

if [ -z "$SUPABASE_URL" ] || [ -z "$SUPABASE_KEY" ]; then
    echo -e "${RED}Error: SUPABASE_URL and SUPABASE_KEY must be set in .env${NC}"
    exit 1
fi

# Check if functions-framework is installed
if ! command -v functions-framework &> /dev/null; then
    echo -e "${RED}Error: functions-framework is not installed.${NC}"
    echo "Please run: pip install functions-framework"
    exit 1
fi

# Run the function
# We need to set PYTHONPATH so it can find the src module
export PYTHONPATH="$PROJECT_ROOT"

echo -e "${GREEN}Function is running!${NC}"
echo -e "Send POST requests to: http://localhost:$PORT"
echo ""

functions-framework --target="$FUNCTION_TARGET" --port="$PORT" --debug --source="$SCRIPT_DIR/main.py"
