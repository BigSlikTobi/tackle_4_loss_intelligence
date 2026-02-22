#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<USAGE
Usage: $0 --tenant <tenant_id>

Creates local NightLedger runtime folders outside git-tracked source.

Environment variables:
  NIGHTLEDGER_HOME   Override default runtime home.
USAGE
}

tenant_id=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tenant)
      tenant_id="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$tenant_id" ]]; then
  echo "Error: --tenant is required" >&2
  usage
  exit 1
fi

if [[ -n "${NIGHTLEDGER_HOME:-}" ]]; then
  nl_home="$NIGHTLEDGER_HOME"
else
  config_home="${XDG_CONFIG_HOME:-$HOME/.config}"
  nl_home="$config_home/nightledger"
fi

tenant_root="$nl_home/tenants/$tenant_id"
rules_file="$tenant_root/rules_runtime.yaml"

mkdir -p "$tenant_root/audit"

if [[ ! -f "$nl_home/config.yaml" ]]; then
  cat > "$nl_home/config.yaml" <<CFG
# NightLedger local runtime config
server:
  host: 127.0.0.1
  port: 8787

policy:
  catalog_refresh_seconds: 300
CFG
fi

if [[ ! -f "$rules_file" ]]; then
  cat > "$rules_file" <<RULES
version: 1
tenant_id: "$tenant_id"
rules: []
RULES
fi

echo "Bootstrapped NightLedger local runtime"
echo "  NIGHTLEDGER_HOME: $nl_home"
echo "  Tenant: $tenant_id"
echo "  Rules file: $rules_file"
