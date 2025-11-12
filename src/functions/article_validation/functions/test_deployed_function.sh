#!/usr/bin/env bash
# Test the deployed article validation Cloud Function with grounding
#!/usr/bin/env bash

set -euo pipefail

FUNCTION_URL="https://article-validation-hjm4dt4a5q-uc.a.run.app"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}============================================================${NC}"
echo -e "${BLUE}Testing Deployed Cloud Function${NC}"
echo -e "${BLUE}============================================================${NC}"
echo ""

if [ -z "${GEMINI_API_KEY:-}" ]; then
    echo -e "${RED}ERROR: GEMINI_API_KEY environment variable not set${NC}"
    echo "Please set your Gemini API key:"
    echo "  export GEMINI_API_KEY='your-api-key-here'"
    exit 1
fi

echo -e "${GREEN}✓ API Key found${NC}"
echo -e "${YELLOW}Function URL: ${FUNCTION_URL}${NC}"
echo ""

echo -e "${BLUE}Sending test request with grounding enabled...${NC}"
echo ""

RESPONSE=$(curl -s -X POST "${FUNCTION_URL}" \
  -H 'Content-Type: application/json' \
  -d "{
    \"article\": {
      \"headline\": \"Kansas City Chiefs Rally for Victory Against Raiders\",
      \"sub_header\": \"Mahomes leads comeback in thrilling divisional matchup\",
      \"introduction_paragraph\": \"The Kansas City Chiefs secured a dramatic 31-28 victory over the Las Vegas Raiders on Sunday, with Patrick Mahomes orchestrating a fourth-quarter comeback at Arrowhead Stadium.\",
      \"content\": [
        \"Patrick Mahomes threw for 348 yards and three touchdowns, including the game-winning 25-yard strike to Travis Kelce with 1:47 remaining in the fourth quarter.\",
        \"Travis Kelce finished with eight receptions for 115 yards and two touchdowns.\"
      ]
    },
    \"article_type\": \"team_article\",
    \"llm\": {
      \"api_key\": \"${GEMINI_API_KEY}\",
      \"model\": \"gemini-2.5-flash-lite\",
      \"enable_web_search\": true,
      \"timeout_seconds\": 60
    },
    \"validation_config\": {
      \"enable_factual\": true,
      \"enable_contextual\": true,
      \"enable_quality\": true,
      \"timeout_seconds\": 90
    }
  }")

echo -e "${GREEN}Response received!${NC}"
echo ""

# Parse and display results
echo "$RESPONSE" | python3 -c "
import json
import sys

try:
    data = json.load(sys.stdin)
    
    print('Status:', data.get('status', 'unknown'))
    print('Decision:', data.get('decision', 'unknown'))
    print('Releasable:', data.get('is_releasable', False))
    print('Processing Time:', data.get('processing_time_ms', 0), 'ms')
    print()
    
    factual = data.get('factual', {})
    contextual = data.get('contextual', {})
    quality = data.get('quality', {})
    
    print('Scores:')
    print(f\"  Factual:    {factual.get('score', 0):.2f} (enabled: {factual.get('enabled', False)})\")
    print(f\"  Contextual: {contextual.get('score', 0):.2f} (enabled: {contextual.get('enabled', False)})\")
    print(f\"  Quality:    {quality.get('score', 0):.2f} (enabled: {quality.get('enabled', False)})\")
    print()
    
    # Check for factual details (claims identification)
    factual_details = factual.get('details', {})
    if factual_details:
        print('Claims Identification:')
        print(f\"  Total Claims: {factual_details.get('claims_total', 0)}\")
        print(f\"  Claims Checked: {factual_details.get('claims_checked', 0)}\")
        print(f\"  Verified: {factual_details.get('verified', 0)}\")
        print(f\"  Contradicted: {factual_details.get('contradicted', 0)}\")
        print(f\"  Uncertain: {factual_details.get('uncertain', 0)}\")
    
    if data.get('error'):
        print()
        print('Error:', data['error'])
    
except Exception as e:
    print('Failed to parse response:', e)
    print()
    print('Raw response:')
    print(sys.stdin.read())
"

echo ""
echo -e "${BLUE}============================================================${NC}"
echo -e "${GREEN}✓ Cloud Function test complete!${NC}"
echo -e "${BLUE}============================================================${NC}"
