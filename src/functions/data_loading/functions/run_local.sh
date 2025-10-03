#!/bin/bash

# Local Testing Script for Firebase Cloud Function
# This script runs the function locally using functions-framework

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Navigate to functions directory
cd "$(dirname "$0")"

# Check Python version
PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d'.' -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d'.' -f2)

if [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -ge 13 ]; then
    warn "You are using Python $PYTHON_VERSION"
    warn "functions-framework has compatibility issues with Python 3.13"
    warn "The function will still deploy to Cloud Functions (which uses Python 3.12)"
    echo ""
    info "Options for local testing:"
    echo "  1. Install Python 3.12: brew install python@3.12"
    echo "  2. Skip local testing and deploy directly: ./deploy.sh"
    echo "  3. Continue anyway (may fail)"
    echo ""
    read -p "Continue with Python $PYTHON_VERSION? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    info "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
info "Activating virtual environment..."
source venv/bin/activate

# Install dependencies
info "Installing dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

# Load environment variables if .env file exists
if [ -f "../.env" ]; then
    info "Loading environment variables from ../.env"
    export $(cat ../.env | grep -v '^#' | xargs)
fi

# Start the function
info "Starting function locally on http://localhost:8080"
info "Using main_local.py wrapper for local testing"
info "Press Ctrl+C to stop"
echo ""

# Use main_local.py which handles imports for local testing
functions-framework --target=package_handler --source=main_local.py --debug
