#!/bin/bash
set -e

# Resolve script directory and project root
# SCRIPT_DIR is .../src/functions/fuzzy_search/scripts
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# PROJECT_ROOT is 4 levels up
PROJECT_ROOT="$(dirname "$(dirname "$(dirname "$(dirname "$SCRIPT_DIR")")")")"

# Navigate to project root so we can copy files relative to it
cd "$PROJECT_ROOT"

# Configuration
FUNCTION_NAME="fuzzy_search"
REGION="us-central1"
RUNTIME="python311"
ENTRY_POINT="fuzzy_search"
SOURCE_MODULE="src/functions/fuzzy_search"
# Build dist inside the scripts folder
DIST_DIR="$SCRIPT_DIR/dist"

echo "🚀 Starting deployment for $FUNCTION_NAME..."
echo "📂 Project Root: $PROJECT_ROOT"
echo "📂 Build Dir:    $DIST_DIR"

# Cleanup previous build
rm -rf "$DIST_DIR"
mkdir -p "$DIST_DIR"

# Copy main function code
# main.py is in src/functions/fuzzy_search/functions/main.py
echo "📦 Packaging files..."
cp "$SOURCE_MODULE/functions/main.py" "$DIST_DIR/main.py"

# Copy requirements
cp "$SOURCE_MODULE/requirements.txt" "$DIST_DIR/requirements.txt"
echo "functions-framework>=3.0.0" >> "$DIST_DIR/requirements.txt"

# Copy source code (preserving structure but only relevant parts)
# We need to recreate the directory structure src/functions/fuzzy_search and src/shared
mkdir -p "$DIST_DIR/src/functions"

# Copy shared modules
cp -r src/shared "$DIST_DIR/src/"

# Copy fuzzy_search module
cp -r "$SOURCE_MODULE" "$DIST_DIR/src/functions/"

# Ensure __init__.py files exist for valid packaging
[ -f src/__init__.py ] && cp src/__init__.py "$DIST_DIR/src/"
[ -f src/functions/__init__.py ] && cp src/functions/__init__.py "$DIST_DIR/src/functions/"

# Verify structure
echo "📂 Build structure:"
ls -F "$DIST_DIR"
ls -F "$DIST_DIR/src"

# Deploy
echo "☁️  Deploying to Google Cloud Functions..."
cd "$DIST_DIR"

# Convert local .env to .env.yaml for GCF
# GCF requires YAML format: KEY: "VALUE"
if [ -f "$PROJECT_ROOT/.env" ]; then
    echo "🔑 Generating env vars from .env..."
    
    # Use python to safely convert .env to simple YAML key-value pairs
    python3 -c "
import sys
import os

print('🐍 Starting Python .env parser...', file=sys.stderr)
# Try to use python-dotenv for robust parsing
try:
    from dotenv import dotenv_values
    config = dotenv_values('$PROJECT_ROOT/.env')
    print(f'✅ Loaded {len(config)} keys using python-dotenv', file=sys.stderr)
except ImportError:
    # Fallback to manual parsing if dotenv is not installed
    print('⚠️  python-dotenv not found, using manual parsing', file=sys.stderr)
    config = {}
    try:
        with open('$PROJECT_ROOT/.env', 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'): continue
                if '=' in line:
                    k, v = line.split('=', 1)
                    k = k.strip()
                    v = v.strip()
                    
                    # Remove inline comments (simple heuristic)
                    if ' #' in v:
                        v = v.split(' #', 1)[0].strip()
                    
                    # Remove quotes
                    if (v.startswith('\"') and v.endswith('\"')) or (v.startswith(\"'\") and v.endswith(\"'\")):
                        v = v[1:-1]
                    
                    config[k] = v
        print(f'✅ Loaded {len(config)} keys manually', file=sys.stderr)
    except Exception as e:
        print(f'❌ Error reading .env: {e}', file=sys.stderr)
        sys.exit(1)

# Write to YAML
try:
    with open('.env.yaml', 'w') as f:
        for k, v in config.items():
            if v is None: v = ''
            # Escape quotes in value
            v_str = str(v).replace('\"', '\\\"')
            f.write(f'{k}: \"{v_str}\"\n')
    print('✅ Written .env.yaml', file=sys.stderr)
except Exception as e:
    print(f'❌ Error writing .env.yaml: {e}', file=sys.stderr)
    sys.exit(1)
"
    
    ENV_FLAG="--env-vars-file=.env.yaml"
else
    echo "⚠️  No .env file found at project root! Deployment may fail if env vars are missing."
    ENV_FLAG=""
fi

# Print command for debugging
CMD="gcloud functions deploy $FUNCTION_NAME \
    --gen2 \
    --region=$REGION \
    --runtime=$RUNTIME \
    --source=. \
    --entry-point=$ENTRY_POINT \
    --trigger-http \
    --allow-unauthenticated \
    $ENV_FLAG"

echo "Running: $CMD"
$CMD

# Cleanup secrets
[ -f .env.yaml ] && rm .env.yaml

echo "✅ Deployment complete!"
