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
FILE="${2:?path to a proposed file, directory, or files JSON}"
SUMMARY="${3:-candidate from allowed_files}"
python3 - "$KERNEL" "$PRINCIPAL" "$CASE_ID" "$FILE" "$SUMMARY" <<'PY'
import json, sys, urllib.error, urllib.request
from pathlib import Path

kernel, principal, case_id, path, summary = sys.argv[1:]
src = Path(path)
files = {}
if src.is_dir():
    for item in src.rglob("*"):
        if item.is_file():
            files[str(item.relative_to(src))] = item.read_text(encoding="utf-8")
elif src.suffix == ".json":
    loaded = json.loads(src.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        sys.stderr.write("files JSON must be an object of {relative_path: contents}\n")
        sys.exit(1)
    files = {str(key): str(value) for key, value in loaded.items()}
else:
    files[src.name] = src.read_text(encoding="utf-8")
payload = {"summary": summary, "files": files, "risk": "low"}
if "lightrag_store.py" in files:
    payload["lightrag_store_py"] = files["lightrag_store.py"]
body = json.dumps(payload).encode()
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
