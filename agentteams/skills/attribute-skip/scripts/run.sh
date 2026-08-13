#!/usr/bin/env bash
set -euo pipefail
KERNEL="${AGENTMED_KERNEL_URL:-http://host.docker.internal:8088}"
PRINCIPAL="${AGENTMED_PRINCIPAL:-agent:attribution}"
CASE_ID="${1:?case id required}"
curl -sS -X POST "$KERNEL/v1/cases/$CASE_ID/attribute" \
  -H "Content-Type: application/json" \
  -H "X-AgentMED-Principal: $PRINCIPAL" \
  -d '{}'
echo
