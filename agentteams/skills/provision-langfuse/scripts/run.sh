#!/usr/bin/env bash
# Kernel holds Langfuse keys. Workers only receive endpoint/key *references*.
# Unreachable → NEEDS_CONTEXT JSON, exit 0 (do not crash the Case).
set -euo pipefail
KERNEL="${AGENTMED_KERNEL_URL:-http://host.docker.internal:8088}"
PRINCIPAL="${AGENTMED_PRINCIPAL:-agent:investigator}"
python3 - "$KERNEL" "$PRINCIPAL" <<'PY'
import json, sys, urllib.error, urllib.request
kernel, principal = sys.argv[1:]
req = urllib.request.Request(
    f"{kernel}/v1/langfuse/provision",
    data=b"{}",
    headers={"Content-Type": "application/json", "X-AgentMED-Principal": principal},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        print(resp.read().decode())
except urllib.error.HTTPError as exc:
    print(json.dumps({"status": "NEEDS_CONTEXT", "needs_context": True, "reason": f"HTTP {exc.code}", "detail": exc.read().decode()[:500]}))
except urllib.error.URLError as exc:
    print(json.dumps({"status": "NEEDS_CONTEXT", "needs_context": True, "reason": f"Kernel unreachable: {exc}"}))
PY
echo
