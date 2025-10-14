#!/bin/bash
# Deployment script for game analysis Cloud Function
# Deploys the function to Google Cloud Functions

set -e

# Configuration
FUNCTION_NAME="game-analysis"
REGION="us-central1"
RUNTIME="python311"
ENTRY_POINT="analysis_handler"
MEMORY="512MB"
TIMEOUT="60s"

echo "Deploying game analysis Cloud Function..."
echo ""
echo "Configuration:"
echo "  Function: $FUNCTION_NAME"
echo "  Region: $REGION"
echo "  Runtime: $RUNTIME"
echo "  Memory: $MEMORY"
echo "  Timeout: $TIMEOUT"
echo ""

# Ensure we're in the functions directory
cd "$(dirname "$0")"

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    echo "Error: gcloud CLI not found. Please install it first."
    echo "See: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

# Check if user is authenticated
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" &> /dev/null; then
    echo "Error: Not authenticated with gcloud. Run 'gcloud auth login' first."
    exit 1
fi

# Get current project
PROJECT_ID=$(gcloud config get-value project 2>/dev/null)
if [ -z "$PROJECT_ID" ]; then
    echo "Error: No GCP project set. Run 'gcloud config set project PROJECT_ID' first."
    exit 1
fi

echo "Deploying to project: $PROJECT_ID"
echo ""

# Deploy the function
gcloud functions deploy $FUNCTION_NAME \
    --region=$REGION \
    --runtime=$RUNTIME \
    --entry-point=$ENTRY_POINT \
    --trigger-http \
    --allow-unauthenticated \
    --memory=$MEMORY \
    --timeout=$TIMEOUT \
    --source=. \
    --set-env-vars SUPABASE_URL="${SUPABASE_URL}",SUPABASE_KEY="${SUPABASE_KEY}"

echo ""
echo "✓ Deployment complete!"
echo ""
echo "Function URL:"
gcloud functions describe $FUNCTION_NAME --region=$REGION --format="value(httpsTrigger.url)"
echo ""
echo "Test with:"
echo "curl -X POST \$(gcloud functions describe $FUNCTION_NAME --region=$REGION --format='value(httpsTrigger.url)') \\"
echo "  -H 'Content-Type: application/json' \\"
echo "  -d @../test_requests/sample_game.json"
