#!/usr/bin/env bash
set -euo pipefail
KERNEL="${AGENTMED_KERNEL_URL:-http://host.docker.internal:8088}"
if [ "${1:-}" = "--case" ]; then
  CASE_ID="${2:?case id required}"
  curl -sS "$KERNEL/v1/cases/$CASE_ID"
  echo
  exit 0
fi
REF="${1:?github issue url or --case <id> required}"
curl -sS "$KERNEL/v1/cases" --get --data-urlencode "source_ref=$REF"
echo
