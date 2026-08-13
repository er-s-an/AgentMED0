#!/usr/bin/env bash
# Isolated Verifier: GET verifier-context (no Builder CoT) then POST /verify.
set -euo pipefail
KERNEL="${AGENTMED_KERNEL_URL:-http://host.docker.internal:8088}"
PRINCIPAL="${AGENTMED_PRINCIPAL:-agent:verifier}"
CASE_ID="${1:?case id required}"
python3 - "$KERNEL" "$PRINCIPAL" "$CASE_ID" <<'PY'
import sys, urllib.error, urllib.request

kernel, principal, case_id = sys.argv[1:]


def call(method: str, path: str) -> str:
    req = urllib.request.Request(
        f"{kernel}{path}",
        data=b"" if method != "GET" else None,
        headers={"X-AgentMED-Principal": principal},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.read().decode()
    except urllib.error.HTTPError as exc:
        sys.stderr.write(
            f"Kernel error HTTP {exc.code} for {method} {path}: {exc.read().decode() or exc.reason}\n"
        )
        sys.exit(1)
    except urllib.error.URLError as exc:
        sys.stderr.write(f"Kernel unreachable for {method} {path}: {exc}\n")
        sys.exit(1)


context = call("GET", f"/v1/cases/{case_id}/verifier-context")
sys.stdout.write(context)
if not context.endswith("\n"):
    sys.stdout.write("\n")
report = call("POST", f"/v1/cases/{case_id}/verify")
sys.stdout.write(report)
if not report.endswith("\n"):
    sys.stdout.write("\n")
PY
