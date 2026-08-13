#!/usr/bin/env bash
set -euo pipefail
KERNEL="${AGENTMED_KERNEL_URL:-http://host.docker.internal:8088}"
PRINCIPAL="${AGENTMED_PRINCIPAL:-agent:investigator}"
CASE_ID="${1:-}"
echo "Official Langfuse skill is documentation/CLI only. AgentMED workers must not hold LANGFUSE_SECRET_KEY."
echo "Kernel proxy: $KERNEL  principal: $PRINCIPAL"
if [ -n "$CASE_ID" ]; then
  curl -sS "$KERNEL/v1/cases/$CASE_ID/langfuse-traces" \
    -H "X-AgentMED-Principal: $PRINCIPAL"
  echo
else
  curl -sS -X POST "$KERNEL/v1/langfuse/provision" \
    -H "X-AgentMED-Principal: $PRINCIPAL"
  echo
fi
