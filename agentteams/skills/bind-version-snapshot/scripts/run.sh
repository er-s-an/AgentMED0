#!/usr/bin/env bash
# POST Kernel /v1/cases/{id}/investigate as agent:investigator.
set -euo pipefail
KERNEL="${AGENTMED_KERNEL_URL:-http://host.docker.internal:8088}"
PRINCIPAL="${AGENTMED_PRINCIPAL:-agent:investigator}"
CASE_ID="${1:?case id required}"
python3 - "$KERNEL" "$PRINCIPAL" "$CASE_ID" <<'PY'
import sys, urllib.error, urllib.request

kernel, principal, case_id = sys.argv[1:]
req = urllib.request.Request(
    f"{kernel}/v1/cases/{case_id}/investigate",
    data=b"",
    headers={"X-AgentMED-Principal": principal},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=60) as resp:
        sys.stdout.write(resp.read().decode())
        sys.stdout.write("\n")
except urllib.error.HTTPError as exc:
    sys.stderr.write(f"Kernel error HTTP {exc.code} for investigate: {exc.read().decode() or exc.reason}\n")
    sys.exit(1)
except urllib.error.URLError as exc:
    sys.stderr.write(f"Kernel unreachable for investigate: {exc}\n")
    sys.exit(1)
PY
