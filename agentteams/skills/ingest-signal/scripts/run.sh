#!/usr/bin/env bash
set -euo pipefail
KERNEL="${AGENTMED_KERNEL_URL:-http://host.docker.internal:8088}"
PRINCIPAL="${AGENTMED_PRINCIPAL:-agent:intake}"
URL="${1:?github issue url required}"
curl -sS -X POST "$KERNEL/v1/signals/ingest" \
  -H "Content-Type: application/json" \
  -H "X-AgentMED-Principal: $PRINCIPAL" \
  -d "{\"url\":\"$URL\"}"
echo
