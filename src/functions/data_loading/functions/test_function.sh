#!/bin/bash

# Quick test script for the deployed function
# Usage: ./test_function.sh [FUNCTION_URL]

set -e

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Get function URL if not provided
if [ -z "$1" ]; then
    FUNCTION_URL="http://localhost:8080"
    info "No URL provided, testing local function at $FUNCTION_URL"
else
    FUNCTION_URL="$1"
    info "Testing function at $FUNCTION_URL"
fi

# Test with sample request
info "Sending test request..."

RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$FUNCTION_URL" \
  -H "Content-Type: application/json" \
  -d @../requests/player_weekly_stats_package.json)

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | head -n -1)

if [ "$HTTP_CODE" -eq 200 ]; then
    info "✅ Success! HTTP Status: $HTTP_CODE"
    echo ""
    echo "Response:"
    echo "$BODY" | python3 -m json.tool
else
    error "❌ Failed! HTTP Status: $HTTP_CODE"
    echo ""
    echo "Response:"
    echo "$BODY"
    exit 1
fi
