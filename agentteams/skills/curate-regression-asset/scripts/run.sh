#!/usr/bin/env bash
# POST Kernel /v1/cases/{id}/close as agent:curator.
set -euo pipefail
KERNEL="${AGENTMED_KERNEL_URL:-http://host.docker.internal:8088}"
PRINCIPAL="${AGENTMED_PRINCIPAL:-agent:curator}"
CASE_ID="${1:?case id required}"
SUMMARY="${2:-Regression asset: LightRAG must persist file_id on insert and filter query by selection.}"
python3 - "$KERNEL" "$PRINCIPAL" "$CASE_ID" "$SUMMARY" <<'PY'
import json, sys, urllib.error, urllib.request

kernel, principal, case_id, summary = sys.argv[1:]
body = json.dumps({"summary": summary}).encode()
req = urllib.request.Request(
    f"{kernel}/v1/cases/{case_id}/close",
    data=body,
    headers={
        "Content-Type": "application/json",
        "X-AgentMED-Principal": principal,
    },
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=60) as resp:
        sys.stdout.write(resp.read().decode())
        sys.stdout.write("\n")
except urllib.error.HTTPError as exc:
    sys.stderr.write(f"Kernel error HTTP {exc.code} for close: {exc.read().decode() or exc.reason}\n")
    sys.exit(1)
except urllib.error.URLError as exc:
    sys.stderr.write(f"Kernel unreachable for close: {exc}\n")
    sys.exit(1)
PY
