#!/bin/bash
# Re-deployment script for failed services only

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

info() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }
section() { echo -e "\n${BLUE}[SECTION]${NC} $1\n"; }

# Failed services only
SERVICES=(
  "Team Article Generation:src/functions/team_article_generation/functions/deploy.sh"
  "Article Translation:src/functions/article_translation/functions/deploy.sh"
)

DEPLOYED=()
FAILED=()

deploy_service() {
  local service_name="$1"
  local script_path="$2"
  local absolute_script="${PROJECT_ROOT}/${script_path}"

  if [ ! -f "$absolute_script" ]; then
    warn "Missing deploy script for ${service_name} at ${script_path}"
    return 1
  fi

  if [ ! -x "$absolute_script" ]; then
    chmod +x "$absolute_script"
  fi

  section "Deploying ${service_name}"

  if bash "$absolute_script"; then
    info "✅ ${service_name} deployed successfully"
    DEPLOYED+=("$service_name")
    return 0
  else
    error "❌ ${service_name} deployment failed"
    FAILED+=("$service_name")
    return 1
  fi
}

# Pre-flight checks
if ! command -v gcloud >/dev/null 2>&1; then
  error "gcloud CLI not found. Install the Cloud SDK first."
  exit 1
fi

ACTIVE_ACCOUNT=$(gcloud auth list --filter=status:ACTIVE --format="value(account)")
if [ -z "$ACTIVE_ACCOUNT" ]; then
  error "No active gcloud account. Run 'gcloud auth login' first."
  exit 1
fi

PROJECT_ID=$(gcloud config get-value project 2>/dev/null)
if [ -z "$PROJECT_ID" ]; then
  error "No GCP project configured. Run 'gcloud config set project PROJECT_ID'."
  exit 1
fi

section "Re-deploying failed services"
info "Project: ${PROJECT_ID}"
info "Account: ${ACTIVE_ACCOUNT}"
info "Services to deploy: ${#SERVICES[@]}"

# Deploy each service
for entry in "${SERVICES[@]}"; do
  service_name="${entry%%:*}"
  script_path="${entry#*:}"
  
  deploy_service "$service_name" "$script_path"
  
  # Brief pause between deployments
  sleep 2
done

# Summary
section "Re-deployment Summary"

if [ "${#DEPLOYED[@]}" -gt 0 ]; then
  info "Successfully deployed (${#DEPLOYED[@]}):"
  for service in "${DEPLOYED[@]}"; do
    echo "  ✅ $service"
  done
fi

if [ "${#FAILED[@]}" -gt 0 ]; then
  error "Failed (${#FAILED[@]}):"
  for service in "${FAILED[@]}"; do
    echo "  ❌ $service"
  done
  echo ""
  error "Re-deployment completed with failures"
  exit 1
fi

echo ""
info "All failed services re-deployed successfully! 🚀"
