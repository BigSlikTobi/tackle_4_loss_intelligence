#!/bin/bash
# Deployment script for story grouping Cloud Function

set -e

# Configuration
FUNCTION_NAME="story-grouping"
REGION="us-central1"
RUNTIME="python310"
ENTRY_POINT="group_stories"
MEMORY="512MB"
TIMEOUT="60s"

# Paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
BUILD_DIR="$MODULE_ROOT/deploy_build"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${YELLOW}Deploying $FUNCTION_NAME...${NC}"

# Check for .env file
if [ -f "$PROJECT_ROOT/.env" ]; then
    echo "Loading environment variables from .env"
    SUPABASE_URL=$(grep "^SUPABASE_URL=" "$PROJECT_ROOT/.env" | cut -d '=' -f2- | tr -d '"' | tr -d "'")
    SUPABASE_KEY=$(grep "^SUPABASE_KEY=" "$PROJECT_ROOT/.env" | cut -d '=' -f2- | tr -d '"' | tr -d "'")
else
    echo -e "${RED}Error: .env file not found at $PROJECT_ROOT/.env${NC}"
    exit 1
fi

if [ -z "$SUPABASE_URL" ] || [ -z "$SUPABASE_KEY" ]; then
    echo -e "${RED}Error: SUPABASE_URL and SUPABASE_KEY must be set in .env${NC}"
    exit 1
fi

# Create build directory
echo "Creating build directory at $BUILD_DIR..."
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

# Copy source code
echo "Copying source code..."
# Copy the entire src tree to maintain package structure
mkdir -p "$BUILD_DIR/src"
cp -r "$PROJECT_ROOT/src" "$BUILD_DIR/"

# Copy requirements
cp "$MODULE_ROOT/requirements.txt" "$BUILD_DIR/"

# Move main.py to root of build as the entry point
# We rely on the fact that we copied src/ above, so src.functions... imports work
cp "$SCRIPT_DIR/main.py" "$BUILD_DIR/main.py"

# Deployment
echo -e "${YELLOW}Submitting build to Cloud Functions...${NC}"

# Ensure gcloud is available
if ! command -v gcloud &> /dev/null; then
    echo -e "${RED}Error: gcloud CLI is not installed.${NC}"
    exit 1
fi

# Deploy
cd "$BUILD_DIR"

if [ "$1" == "--dry-run" ]; then
    echo -e "${GREEN}Build successful! (Dry run, skipping gcloud deploy)${NC}"
    echo "Build artifacts are in: $BUILD_DIR"
    exit 0
fi

gcloud functions deploy "$FUNCTION_NAME" \
    --gen2 \
    --region="$REGION" \
    --runtime="$RUNTIME" \
    --entry-point="$ENTRY_POINT" \
    --source="." \
    --trigger-http \
    --allow-unauthenticated \
    --memory="$MEMORY" \
    --timeout="$TIMEOUT" \
    --set-env-vars "SUPABASE_URL=$SUPABASE_URL,SUPABASE_KEY=$SUPABASE_KEY"

echo -e "${GREEN}Deployment complete!${NC}"
echo "Cleaning up..."
rm -rf "$BUILD_DIR"

