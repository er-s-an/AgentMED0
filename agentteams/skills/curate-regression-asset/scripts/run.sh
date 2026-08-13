#!/usr/bin/env bash
set -euo pipefail
KERNEL="${AGENTMED_KERNEL_URL:-http://host.docker.internal:8088}"
PRINCIPAL="${AGENTMED_PRINCIPAL:-agent:curator}"
CASE_ID="${1:?case id required}"
SUMMARY="${2:-Regression asset: LightRAG must persist file_id on insert and filter query by selection.}"
python3 - "$KERNEL" "$PRINCIPAL" "$CASE_ID" "$SUMMARY" <<'PY'
import json, sys, urllib.request
kernel, principal, case_id, summary = sys.argv[1:]
body = json.dumps({"summary": summary}).encode()
req = urllib.request.Request(
    f"{kernel}/v1/cases/{case_id}/close",
    data=body,
    headers={"Content-Type": "application/json", "X-AgentMED-Principal": principal},
    method="POST",
)
print(urllib.request.urlopen(req).read().decode())
PY
