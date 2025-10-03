#!/bin/bash
# Deploy content summarization function to Google Cloud Functions

set -e

# Configuration
PROJECT_ID="your-gcp-project-id"
REGION="us-central1"
FUNCTION_NAME="content-summarization"
RUNTIME="python312"
MEMORY="512MB"
TIMEOUT="540s"  # 9 minutes (max for 2nd gen)
MIN_INSTANCES=0
MAX_INSTANCES=10

echo "=== Deploying Content Summarization Function ==="
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Function: $FUNCTION_NAME"
echo ""

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    echo "Error: gcloud CLI not found. Please install it first."
    exit 1
fi

# Set project
gcloud config set project "$PROJECT_ID"

# Deploy function
echo "Deploying function..."
gcloud functions deploy "$FUNCTION_NAME" \
    --gen2 \
    --runtime="$RUNTIME" \
    --region="$REGION" \
    --source=. \
    --entry-point=summarize_content \
    --trigger-http \
    --allow-unauthenticated \
    --memory="$MEMORY" \
    --timeout="$TIMEOUT" \
    --min-instances="$MIN_INSTANCES" \
    --max-instances="$MAX_INSTANCES" \
    --set-env-vars="LOG_LEVEL=INFO" \
    --set-secrets="GEMINI_API_KEY=GEMINI_API_KEY:latest,SUPABASE_URL=SUPABASE_URL:latest,SUPABASE_KEY=SUPABASE_KEY:latest"

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "To test the function:"
echo "  curl -X POST https://$REGION-$PROJECT_ID.cloudfunctions.net/$FUNCTION_NAME \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"limit\": 5}'"
echo ""
echo "To view logs:"
echo "  gcloud functions logs read $FUNCTION_NAME --region=$REGION --limit=50"
