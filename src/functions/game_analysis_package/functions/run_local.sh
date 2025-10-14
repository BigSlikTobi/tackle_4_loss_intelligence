#!/bin/bash
# Local testing script for game analysis Cloud Function
# Runs the function locally using Flask for development and testing

set -e

echo "Starting local game analysis server..."
echo ""
echo "Server will start on http://localhost:8080"
echo "Test with: curl -X POST http://localhost:8080 -H 'Content-Type: application/json' -d @../test_requests/sample_game.json"
echo ""

# Ensure we're in the functions directory
cd "$(dirname "$0")"

# Export port
export PORT=8080

# Run the function locally
python main.py
