#!/usr/bin/env bash
# Test script for article validation with grounding and claims identification

set -euo pipefail

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_REQUESTS_DIR="${SCRIPT_DIR}/test_requests"
OUTPUT_DIR="${SCRIPT_DIR}/test_output"
CLI_SCRIPT="${SCRIPT_DIR}/scripts/validate_cli.py"

# Create output directory
mkdir -p "${OUTPUT_DIR}"

echo -e "${BLUE}==================================================================${NC}"
echo -e "${BLUE}Article Validation Test Suite${NC}"
echo -e "${BLUE}Testing: Grounding (Google Search) and Claims Identification${NC}"
echo -e "${BLUE}==================================================================${NC}"
echo ""

# Check if API key is set
if [ -z "${GEMINI_API_KEY:-}" ]; then
    echo -e "${RED}ERROR: GEMINI_API_KEY environment variable not set${NC}"
    echo "Please set your Gemini API key:"
    echo "  export GEMINI_API_KEY='your-api-key-here'"
    exit 1
fi

echo -e "${GREEN}✓ GEMINI_API_KEY found${NC}"
echo ""

# Test 1: Minimal validation (basic functionality)
echo -e "${YELLOW}Test 1: Minimal Validation (Basic Functionality)${NC}"
echo "Testing: ${TEST_REQUESTS_DIR}/minimal_validation.json"
python "${CLI_SCRIPT}" \
    --payload "${TEST_REQUESTS_DIR}/minimal_validation.json" \
    --output "${OUTPUT_DIR}/test1_minimal.json" \
    --log-level INFO \
    --summary
echo -e "${GREEN}✓ Test 1 completed${NC}"
echo ""

# Test 2: Sample validation with grounding enabled
echo -e "${YELLOW}Test 2: Sample Validation with Google Search Grounding${NC}"
echo "Testing: ${TEST_REQUESTS_DIR}/sample_validation.json"
echo "Features: Web search enabled, full validation pipeline"
python "${CLI_SCRIPT}" \
    --payload "${TEST_REQUESTS_DIR}/sample_validation.json" \
    --enable-web-search true \
    --output "${OUTPUT_DIR}/test2_grounding.json" \
    --log-level DEBUG \
    --summary
echo -e "${GREEN}✓ Test 2 completed${NC}"
echo ""

# Test 3: Custom standards validation
echo -e "${YELLOW}Test 3: Custom Standards Validation${NC}"
echo "Testing: ${TEST_REQUESTS_DIR}/custom_standards.json"
python "${CLI_SCRIPT}" \
    --payload "${TEST_REQUESTS_DIR}/custom_standards.json" \
    --enable-web-search true \
    --output "${OUTPUT_DIR}/test3_custom_standards.json" \
    --log-level INFO \
    --summary
echo -e "${GREEN}✓ Test 3 completed${NC}"
echo ""

# Extract and display claims from the sample validation output
echo -e "${BLUE}==================================================================${NC}"
echo -e "${BLUE}Claims Identification Analysis${NC}"
echo -e "${BLUE}==================================================================${NC}"
echo ""

if [ -f "${OUTPUT_DIR}/test2_grounding.json" ]; then
    echo -e "${YELLOW}Analyzing claims from sample validation...${NC}"
    python3 << 'EOF'
import json
import sys

output_file = sys.argv[1]

with open(output_file, 'r') as f:
    report = json.load(f)

factual = report.get('factual', {})
details = factual.get('details', {})

print(f"Factual Validation Score: {factual.get('score', 0):.2f}")
print(f"Confidence: {factual.get('confidence', 0):.2f}")
print(f"Passed: {factual.get('passed', False)}")
print()

selection = details.get('selection_counts', {})
print(f"Claims Considered: {selection.get('considered', 0)}")
print(f"Claims Selected for Verification: {selection.get('selected', 0)}")
print(f"Deferred (Capacity): {selection.get('deferred_capacity', 0)}")
print(f"Deferred (Low Priority): {selection.get('deferred_low_priority', 0)}")
print()

print(f"Verification Results:")
print(f"  Verified: {details.get('verified', 0)}")
print(f"  Contradicted: {details.get('contradicted', 0)}")
print(f"  Uncertain: {details.get('uncertain', 0)}")
print(f"  Errors: {details.get('errors', 0)}")
print()

# Show selected claims with priority scores
selected_claims = details.get('selected_claims', {})
items = selected_claims.get('items', [])
if items:
    print("Selected Claims (with priority scores):")
    for i, claim in enumerate(items, 1):
        print(f"\n{i}. [{claim.get('category', 'unknown')}] Score: {claim.get('score', 0):.3f}")
        print(f"   Text: {claim.get('text', 'N/A')}")
        reasons = claim.get('reasons', [])
        if reasons:
            print(f"   Priority Reasons: {', '.join(reasons)}")
else:
    print("No selected claims found in output")

# Show issues
issues = factual.get('issues', [])
if issues:
    print(f"\n\nFactual Issues Found: {len(issues)}")
    for i, issue in enumerate(issues, 1):
        print(f"\n{i}. [{issue.get('severity', 'unknown')}] {issue.get('message', 'N/A')}")
        if issue.get('source_url'):
            print(f"   Source: {issue['source_url']}")
        if issue.get('suggestion'):
            print(f"   Suggestion: {issue['suggestion']}")
else:
    print("\n\nNo factual issues found")

EOF
    python3 -c "import sys; print(sys.argv)" "${OUTPUT_DIR}/test2_grounding.json" > /dev/null
    python3 -c "
import json
import sys

output_file = '${OUTPUT_DIR}/test2_grounding.json'

with open(output_file, 'r') as f:
    report = json.load(f)

factual = report.get('factual', {})
details = factual.get('details', {})

print(f\"Factual Validation Score: {factual.get('score', 0):.2f}\")
print(f\"Confidence: {factual.get('confidence', 0):.2f}\")
print(f\"Passed: {factual.get('passed', False)}\")
print()

selection = details.get('selection_counts', {})
print(f\"Claims Considered: {selection.get('considered', 0)}\")
print(f\"Claims Selected for Verification: {selection.get('selected', 0)}\")
print(f\"Deferred (Capacity): {selection.get('deferred_capacity', 0)}\")
print(f\"Deferred (Low Priority): {selection.get('deferred_low_priority', 0)}\")
print()

print(f\"Verification Results:\")
print(f\"  Verified: {details.get('verified', 0)}\")
print(f\"  Contradicted: {details.get('contradicted', 0)}\")
print(f\"  Uncertain: {details.get('uncertain', 0)}\")
print(f\"  Errors: {details.get('errors', 0)}\")
print()

# Show selected claims with priority scores
selected_claims = details.get('selected_claims', {})
items = selected_claims.get('items', [])
if items:
    print(\"Selected Claims (with priority scores):\")
    for i, claim in enumerate(items, 1):
        print(f\"\n{i}. [{claim.get('category', 'unknown')}] Score: {claim.get('score', 0):.3f}\")
        print(f\"   Text: {claim.get('text', 'N/A')}\")
        reasons = claim.get('reasons', [])
        if reasons:
            print(f\"   Priority Reasons: {', '.join(reasons)}\")
else:
    print(\"No selected claims found in output\")

# Show issues
issues = factual.get('issues', [])
if issues:
    print(f\"\n\nFactual Issues Found: {len(issues)}\")
    for i, issue in enumerate(issues, 1):
        print(f\"\n{i}. [{issue.get('severity', 'unknown')}] {issue.get('message', 'N/A')}\")
        if issue.get('source_url'):
            print(f\"   Source: {issue['source_url']}\")
        if issue.get('suggestion'):
            print(f\"   Suggestion: {issue['suggestion']}\")
else:
    print(\"\n\nNo factual issues found\")
"
else
    echo -e "${RED}Output file not found: ${OUTPUT_DIR}/test2_grounding.json${NC}"
fi

echo ""
echo -e "${BLUE}==================================================================${NC}"
echo -e "${BLUE}Test Summary${NC}"
echo -e "${BLUE}==================================================================${NC}"
echo ""
echo "Output files created:"
ls -lh "${OUTPUT_DIR}"/*.json 2>/dev/null || echo "No output files found"
echo ""
echo -e "${GREEN}All tests completed!${NC}"
echo ""
echo "To view detailed results:"
echo "  cat ${OUTPUT_DIR}/test2_grounding.json | jq ."
echo ""
echo "To view claims details specifically:"
echo "  cat ${OUTPUT_DIR}/test2_grounding.json | jq '.factual.details.selected_claims'"
