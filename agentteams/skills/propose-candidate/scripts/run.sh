#!/usr/bin/env bash
set -euo pipefail
KERNEL="${AGENTMED_KERNEL_URL:-http://host.docker.internal:8088}"
PRINCIPAL="${AGENTMED_PRINCIPAL:-agent:builder}"
CASE_ID="${1:?case id required}"
if [ $# -lt 2 ]; then
  curl -sS "$KERNEL/v1/cases/$CASE_ID/builder-context" \
    -H "X-AgentMED-Principal: $PRINCIPAL"
  echo
  exit 0
fi
FILE="${2:?path to proposed lightrag_store.py required}"
SUMMARY="${3:-store file_id on insert and filter query by selected file_ids}"
python3 - "$KERNEL" "$PRINCIPAL" "$CASE_ID" "$FILE" "$SUMMARY" <<'PY'
import json, sys, urllib.request
kernel, principal, case_id, path, summary = sys.argv[1:]
source = open(path, encoding="utf-8").read()
body = json.dumps({"summary": summary, "lightrag_store_py": source, "diff": "see files", "risk": "low"}).encode()
req = urllib.request.Request(
    f"{kernel}/v1/cases/{case_id}/candidates",
    data=body,
    headers={"Content-Type": "application/json", "X-AgentMED-Principal": principal},
    method="POST",
)
print(urllib.request.urlopen(req).read().decode())
PY
