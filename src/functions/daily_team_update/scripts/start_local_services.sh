#!/bin/bash
# Helper script to launch all downstream service run_local servers used by the daily team update pipeline.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"
LOG_DIR="${PROJECT_ROOT}/.local_service_logs"

SERVICES=(
  "URL Content Extraction:src/functions/url_content_extraction/functions/run_local.sh:8101"
  "Article Summarization:src/functions/article_summarization/functions/run_local.sh:8102"
  "Team Article Generation:src/functions/team_article_generation/functions/run_local.sh:8103"
  "Article Translation:src/functions/article_translation/functions/run_local.sh:8104"
  "Image Selection:src/functions/image_selection/functions/run_local.sh:8105"
)

mkdir -p "$LOG_DIR"
PIDS=()

cleanup() {
  echo ""
  echo "Shutting down local services..."
  for pid in "${PIDS[@]:-}"; do
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
      wait "$pid" 2>/dev/null || true
    fi
  done
  echo "Logs available in ${LOG_DIR}"
}

trap cleanup INT TERM EXIT

start_service() {
  local service_name="$1"
  local script_path="$2"
  local port="$3"
  local absolute_script="${PROJECT_ROOT}/${script_path}"

  if [ ! -f "$absolute_script" ]; then
    echo "[WARN] Missing run_local script for ${service_name} at ${script_path}"
    return
  fi

  if [ ! -x "$absolute_script" ]; then
    chmod +x "$absolute_script"
  fi

  local log_file="${LOG_DIR}/$(echo "$service_name" | tr ' ' '_' | tr 'A-Z' 'a-z').log"
  echo "[INFO] Starting ${service_name} on port ${port} (logging to ${log_file})"

  (
    cd "$(dirname "$absolute_script")" && \
      PORT="$port" ./"$(basename "$absolute_script")"
  ) >"$log_file" 2>&1 &
  local pid=$!
  PIDS+=("$pid")
}

echo "Launching local services from ${PROJECT_ROOT}" 

for entry in "${SERVICES[@]}"; do
  service_name="${entry%%:*}"
  remainder="${entry#*:}"
  script_path="${remainder%%:*}"
  port="${remainder##*:}"
  start_service "$service_name" "$script_path" "$port"
  sleep 1
done

echo ""
if [ "${#PIDS[@]}" -eq 0 ]; then
  echo "No services started. Check configuration and scripts."
  exit 1
fi

echo "All requested services started. Logs in ${LOG_DIR}."
if command -v lsof >/dev/null 2>&1; then
  echo "Use 'lsof -i :8080' (or the configured ports) to verify listeners."
fi

echo "Press Ctrl+C to stop all services."
wait
