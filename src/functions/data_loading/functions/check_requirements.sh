#!/bin/bash

# Pre-deployment Check Script
# Verifies that everything is ready for deployment

set -e

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "========================================="
echo "  Firebase Function Pre-Deployment Check"
echo "========================================="
echo ""

CHECKS_PASSED=0
CHECKS_FAILED=0

check_pass() {
    echo -e "${GREEN}✓${NC} $1"
    ((CHECKS_PASSED++))
}

check_fail() {
    echo -e "${RED}✗${NC} $1"
    ((CHECKS_FAILED++))
}

check_warn() {
    echo -e "${YELLOW}⚠${NC} $1"
}

# Check gcloud CLI
echo "1. Checking gcloud CLI..."
if command -v gcloud &> /dev/null; then
    VERSION=$(gcloud --version | head -n1)
    check_pass "gcloud CLI is installed ($VERSION)"
else
    check_fail "gcloud CLI is not installed"
    echo "   Install with: brew install --cask google-cloud-sdk"
fi

# Check authentication
echo ""
echo "2. Checking GCP authentication..."
if gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
    ACCOUNT=$(gcloud auth list --filter=status:ACTIVE --format="value(account)")
    check_pass "Authenticated as: $ACCOUNT"
else
    check_fail "Not authenticated with GCP"
    echo "   Run: gcloud auth login"
fi

# Check project
echo ""
echo "3. Checking GCP project..."
PROJECT_ID=$(gcloud config get-value project 2>/dev/null)
if [ -n "$PROJECT_ID" ]; then
    check_pass "Project set: $PROJECT_ID"
else
    check_fail "No GCP project configured"
    echo "   Run: gcloud config set project YOUR_PROJECT_ID"
fi

# Check required files
echo ""
echo "4. Checking required files..."
cd "$(dirname "$0")"

if [ -f "main.py" ]; then
    check_pass "main.py exists"
else
    check_fail "main.py not found"
fi

if [ -f "requirements.txt" ]; then
    check_pass "requirements.txt exists"
else
    check_fail "requirements.txt not found"
fi

if [ -f ".gcloudignore" ]; then
    check_pass ".gcloudignore exists"
else
    check_warn ".gcloudignore not found (optional but recommended)"
fi

# Check for .env.yaml
echo ""
echo "5. Checking environment configuration..."
if [ -f ".env.yaml" ]; then
    check_pass ".env.yaml exists (will use environment variables)"
else
    check_warn ".env.yaml not found (no environment variables will be set)"
    echo "   If you need env vars, copy from: .env.yaml.example"
fi

# Check src directory structure
echo ""
echo "6. Checking source code structure..."
if [ -d "../src/core/packaging" ]; then
    check_pass "src/core/packaging directory exists"
else
    check_fail "src/core/packaging directory not found"
fi

# Check Python version
echo ""
echo "7. Checking Python installation..."
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version)
    check_pass "Python is installed ($PYTHON_VERSION)"
else
    check_warn "Python 3 not found (needed for local testing only)"
fi

# Check APIs (if project is set)
if [ -n "$PROJECT_ID" ]; then
    echo ""
    echo "8. Checking required APIs..."
    
    if gcloud services list --enabled --project="$PROJECT_ID" 2>/dev/null | grep -q "cloudfunctions.googleapis.com"; then
        check_pass "Cloud Functions API is enabled"
    else
        check_fail "Cloud Functions API is not enabled"
        echo "   Run: gcloud services enable cloudfunctions.googleapis.com"
    fi
    
    if gcloud services list --enabled --project="$PROJECT_ID" 2>/dev/null | grep -q "cloudbuild.googleapis.com"; then
        check_pass "Cloud Build API is enabled"
    else
        check_fail "Cloud Build API is not enabled"
        echo "   Run: gcloud services enable cloudbuild.googleapis.com"
    fi
    
    if gcloud services list --enabled --project="$PROJECT_ID" 2>/dev/null | grep -q "run.googleapis.com"; then
        check_pass "Cloud Run API is enabled"
    else
        check_fail "Cloud Run API is not enabled"
        echo "   Run: gcloud services enable run.googleapis.com"
    fi
fi

# Summary
echo ""
echo "========================================="
echo "  Check Summary"
echo "========================================="
echo -e "${GREEN}Passed: $CHECKS_PASSED${NC}"
if [ $CHECKS_FAILED -gt 0 ]; then
    echo -e "${RED}Failed: $CHECKS_FAILED${NC}"
fi
echo ""

if [ $CHECKS_FAILED -eq 0 ]; then
    echo -e "${GREEN}✓ All critical checks passed!${NC}"
    echo "You're ready to deploy. Run: ./deploy.sh"
    exit 0
else
    echo -e "${RED}✗ Some checks failed.${NC}"
    echo "Please fix the issues above before deploying."
    exit 1
fi
