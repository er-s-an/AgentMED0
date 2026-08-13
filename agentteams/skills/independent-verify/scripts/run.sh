#!/usr/bin/env bash
set -euo pipefail
KERNEL="${AGENTMED_KERNEL_URL:-http://host.docker.internal:8088}"
PRINCIPAL="${AGENTMED_PRINCIPAL:-agent:verifier}"
CASE_ID="${1:?case id required}"
curl -sS "$KERNEL/v1/cases/$CASE_ID/verifier-context" -H "X-AgentMED-Principal: $PRINCIPAL"
echo
curl -sS -X POST "$KERNEL/v1/cases/$CASE_ID/verify" -H "X-AgentMED-Principal: $PRINCIPAL"
echo
