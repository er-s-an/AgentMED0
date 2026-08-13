#!/usr/bin/env bash
# Builder: GET builder-context, or POST a sealed CandidateRevision. Never self-verify.
set -euo pipefail
KERNEL="${AGENTMED_KERNEL_URL:-http://host.docker.internal:8088}"
PRINCIPAL="${AGENTMED_PRINCIPAL:-agent:builder}"
CASE_ID="${1:?case id required}"
if [ $# -lt 2 ]; then
  python3 - "$KERNEL" "$PRINCIPAL" "$CASE_ID" <<'PY'
import sys, urllib.error, urllib.request

kernel, principal, case_id = sys.argv[1:]
req = urllib.request.Request(
    f"{kernel}/v1/cases/{case_id}/builder-context",
    headers={"X-AgentMED-Principal": principal},
    method="GET",
)
try:
    with urllib.request.urlopen(req, timeout=60) as resp:
        sys.stdout.write(resp.read().decode())
        sys.stdout.write("\n")
except urllib.error.HTTPError as exc:
    sys.stderr.write(f"Kernel error HTTP {exc.code} for builder-context: {exc.read().decode() or exc.reason}\n")
    sys.exit(1)
except urllib.error.URLError as exc:
    sys.stderr.write(f"Kernel unreachable for builder-context: {exc}\n")
    sys.exit(1)
PY
  exit 0
fi
FILE="${2:?path to proposed lightrag_store.py required}"
SUMMARY="${3:-store file_id on insert and filter query by selected file_ids}"
python3 - "$KERNEL" "$PRINCIPAL" "$CASE_ID" "$FILE" "$SUMMARY" <<'PY'
import json, sys, urllib.error, urllib.request

kernel, principal, case_id, path, summary = sys.argv[1:]
source = open(path, encoding="utf-8").read()
body = json.dumps(
    {"summary": summary, "lightrag_store_py": source, "diff": "see files", "risk": "low"}
).encode()
req = urllib.request.Request(
    f"{kernel}/v1/cases/{case_id}/candidates",
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
    sys.stderr.write(f"Kernel error HTTP {exc.code} for candidates: {exc.read().decode() or exc.reason}\n")
    sys.exit(1)
except urllib.error.URLError as exc:
    sys.stderr.write(f"Kernel unreachable for candidates: {exc}\n")
    sys.exit(1)
PY
