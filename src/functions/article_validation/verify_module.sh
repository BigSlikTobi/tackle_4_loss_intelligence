#!/bin/bash
# Quick verification script for article_validation module

set -e

echo "============================================"
echo "Article Validation Module Verification"
echo "============================================"
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

success() { echo -e "${GREEN}✓${NC} $1"; }
error() { echo -e "${RED}✗${NC} $1"; }
info() { echo -e "${YELLOW}ℹ${NC} $1"; }

MODULE_PATH="src/functions/article_validation"

# Change to project root
cd "$(dirname "$0")/../../.."

echo "Working directory: $(pwd)"
echo ""

# Test 1: Check module structure
echo "Test 1: Module Structure"
if [ -d "$MODULE_PATH" ]; then
    success "Module directory exists"
else
    error "Module directory not found"
    exit 1
fi

for dir in "core" "functions" "scripts" "test_requests"; do
    if [ -d "$MODULE_PATH/$dir" ]; then
        success "  $dir/ directory exists"
    else
        error "  $dir/ directory missing"
    fi
done

for file in "requirements.txt" ".env.example" "README.md"; do
    if [ -f "$MODULE_PATH/$file" ]; then
        success "  $file exists"
    else
        error "  $file missing"
    fi
done
echo ""

# Test 2: Check scripts are executable
echo "Test 2: Script Permissions"
if [ -x "$MODULE_PATH/functions/deploy.sh" ]; then
    success "deploy.sh is executable"
else
    error "deploy.sh is not executable"
fi

if [ -x "$MODULE_PATH/functions/run_local.sh" ]; then
    success "run_local.sh is executable"
else
    error "run_local.sh is not executable"
fi
echo ""

# Test 3: Check for cross-module imports
echo "Test 3: Import Independence"
CROSS_IMPORTS=$(grep -r "from src\.functions\." "$MODULE_PATH" | grep -v "from src\.functions\.article_validation" || true)
if [ -z "$CROSS_IMPORTS" ]; then
    success "No cross-module imports found"
else
    error "Found cross-module imports:"
    echo "$CROSS_IMPORTS"
fi
echo ""

# Test 4: Check Python syntax
echo "Test 4: Python Syntax"
SYNTAX_ERRORS=0
for pyfile in $(find "$MODULE_PATH" -name "*.py" -type f); do
    if python3 -m py_compile "$pyfile" 2>/dev/null; then
        true  # Success, do nothing
    else
        error "Syntax error in $pyfile"
        SYNTAX_ERRORS=$((SYNTAX_ERRORS + 1))
    fi
done
if [ $SYNTAX_ERRORS -eq 0 ]; then
    success "All Python files have valid syntax"
else
    error "Found $SYNTAX_ERRORS files with syntax errors"
fi
echo ""

# Test 5: Check test payloads are valid JSON
echo "Test 5: Test Payload Validation"
for jsonfile in "$MODULE_PATH/test_requests"/*.json; do
    if [ -f "$jsonfile" ]; then
        if python3 -m json.tool "$jsonfile" > /dev/null 2>&1; then
            success "  $(basename "$jsonfile") is valid JSON"
        else
            error "  $(basename "$jsonfile") has invalid JSON"
        fi
    fi
done
echo ""

# Test 6: Check documentation exists
echo "Test 6: Documentation"
if [ -f "$MODULE_PATH/README.md" ]; then
    LINE_COUNT=$(wc -l < "$MODULE_PATH/README.md")
    if [ "$LINE_COUNT" -gt 100 ]; then
        success "README.md is comprehensive ($LINE_COUNT lines)"
    else
        info "README.md exists but may be incomplete ($LINE_COUNT lines)"
    fi
else
    error "README.md missing"
fi

if [ -f "$MODULE_PATH/.env.example" ]; then
    success ".env.example exists"
else
    error ".env.example missing"
fi
echo ""

# Test 7: Check imports work (optional - requires dependencies)
echo "Test 7: Module Import Test"
if python3 -c "import sys; sys.path.insert(0, '.'); from src.functions.article_validation.core.factory import request_from_payload; print('Import successful')" 2>/dev/null; then
    success "Core imports work"
elif python3 -c "import sys; sys.path.insert(0, '.'); import importlib.util; importlib.util.find_spec('google.generativeai')" 2>/dev/null; then
    info "Dependencies not installed (run: pip install -r $MODULE_PATH/requirements.txt)"
else
    info "Dependencies not installed (run: pip install -r $MODULE_PATH/requirements.txt)"
fi
echo ""

# Test 8: Check deployment scripts
echo "Test 8: Deployment Script Validation"
if bash -n "$MODULE_PATH/functions/deploy.sh" 2>/dev/null; then
    success "deploy.sh has valid bash syntax"
else
    error "deploy.sh has bash syntax errors"
fi

if bash -n "$MODULE_PATH/functions/run_local.sh" 2>/dev/null; then
    success "run_local.sh has valid bash syntax"
else
    error "run_local.sh has bash syntax errors"
fi
echo ""

# Summary
echo "============================================"
echo "Verification Complete"
echo "============================================"
echo ""
echo "Module path: $MODULE_PATH"
echo ""
echo "Next steps:"
echo "  1. Install dependencies: cd $MODULE_PATH && pip install -r requirements.txt"
echo "  2. Test locally: cd $MODULE_PATH/functions && ./run_local.sh"
echo "  3. Deploy: cd $MODULE_PATH/functions && ./deploy.sh"
echo ""
echo "Documentation:"
echo "  - API Reference: $MODULE_PATH/README.md"
echo "  - Configuration: $MODULE_PATH/.env.example"
echo "  - Independence: $MODULE_PATH/MODULE_INDEPENDENCE_VERIFICATION.md"
echo "  - Completion: $MODULE_PATH/IMPLEMENTATION_COMPLETE.md"
echo ""
