#!/usr/bin/env bash
# Request Kernel to materialize a local draft PR from a VerifiedCandidate.
# No merge. No git push. Unverified cases must fail non-zero.
set -euo pipefail
KERNEL="${AGENTMED_KERNEL_URL:-http://host.docker.internal:8088}"
PRINCIPAL="${AGENTMED_PRINCIPAL:-agent:lead}"
CASE_ID="${1:?case id required}"
python3 - "$KERNEL" "$PRINCIPAL" "$CASE_ID" <<'PY'
import json, sys, urllib.error, urllib.request

kernel, principal, case_id = sys.argv[1:]
req = urllib.request.Request(
    f"{kernel}/v1/cases/{case_id}/draft-pr",
    data=b"{}",
    headers={
        "Content-Type": "application/json",
        "X-AgentMED-Principal": principal,
    },
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=60) as resp:
        sys.stdout.write(resp.read().decode())
        if not sys.stdout.isatty():
            sys.stdout.write("\n")
except urllib.error.HTTPError as exc:
    detail = exc.read().decode() or exc.reason
    sys.stderr.write(f"Kernel error HTTP {exc.code} for draft-pr (unverified or refused): {detail}\n")
    sys.exit(1)
except urllib.error.URLError as exc:
    sys.stderr.write(f"Kernel unreachable for draft-pr: {exc}\n")
    sys.exit(1)
PY
echo
