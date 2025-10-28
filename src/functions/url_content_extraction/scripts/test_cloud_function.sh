#!/bin/bash
# Quick test script for the deployed Cloud Function

FUNCTION_URL="${1:-https://url-content-extraction-194028302480.us-central1.run.app}"

echo "Testing Cloud Function: ${FUNCTION_URL}"
echo

curl -X POST "${FUNCTION_URL}" \
  -H 'Content-Type: application/json' \
  -d '{
    "urls": [
      {"url": "https://www.nfl.com/news/aaron-glenn-pleased-justin-fields-performance-jets-first-win-noncommittal-starter"}
    ]
  }' | python3 -m json.tool
