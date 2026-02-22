# NightLedger Local Runtime (MCP-Decoupled)

This document starts implementation planning for running **NightLedger as a local app** that is decoupled from Git-managed runtime state.

## Goal

- NightLedger runs locally (or in the same private network) as a long-lived service.
- The agent communicates with NightLedger via MCP/API endpoints.
- Runtime policy and tenant rule state is stored outside this Git repository.
- Git remains only for product source and release updates.

## Runtime Topology

1. `nightledger` local service starts.
2. Agent connects through MCP transport on local network.
3. Agent performs startup handshake:
   - `GET /v1/policy/catalog` (or MCP equivalent),
   - pins `catalog_version`,
   - calls `authorize_action` for protected operations.
4. Policy/rules are loaded from local data directory, not repository files.

## Local Data Contract

Default local data root:

- Linux/macOS: `${XDG_CONFIG_HOME:-$HOME/.config}/nightledger`
- Override: `NIGHTLEDGER_HOME`

Required runtime files:

- `config.yaml` (operator config)
- `tenants/<tenant_id>/rules_runtime.yaml` (tenant policy rules)
- `tenants/<tenant_id>/audit/` (optional local audit artifacts)

These files are intentionally excluded from version control.

## Implementation Start (Phase 0)

This repository now includes a bootstrap helper:

- `scripts/nightledger/bootstrap_local_runtime.sh`

It creates the local folder structure and a starter tenant rules file under the local NightLedger home.

### Usage

```bash
scripts/nightledger/bootstrap_local_runtime.sh --tenant acme
```

Optional override:

```bash
NIGHTLEDGER_HOME=/opt/nightledger scripts/nightledger/bootstrap_local_runtime.sh --tenant acme
```

## Next Phase

1. Add runtime loader in the service to resolve tenant rules from `NIGHTLEDGER_HOME`.
2. Remove any default path assumptions that point to repo-tracked rule files.
3. Expose a health endpoint showing active `catalog_version` and tenant rule source path.
4. Add migration utility to move legacy repo-based runtime rules into local tenant folders.
