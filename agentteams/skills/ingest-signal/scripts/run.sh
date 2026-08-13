#!/usr/bin/env bash
# POST Kernel /v1/signals/ingest as agent:intake. Never invent a GitHub issue.
set -euo pipefail
KERNEL="${AGENTMED_KERNEL_URL:-http://host.docker.internal:8088}"
PRINCIPAL="${AGENTMED_PRINCIPAL:-agent:intake}"
URL="${1:?github issue url required}"
python3 - "$KERNEL" "$PRINCIPAL" "$URL" <<'PY'
import json, sys, urllib.error, urllib.request

kernel, principal, url = sys.argv[1:]
body = json.dumps({"url": url}).encode()
req = urllib.request.Request(
    f"{kernel}/v1/signals/ingest",
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
    sys.stderr.write(f"Kernel error HTTP {exc.code} for ingest-signal: {exc.read().decode() or exc.reason}\n")
    sys.exit(1)
except urllib.error.URLError as exc:
    sys.stderr.write(f"Kernel unreachable for ingest-signal: {exc}\n")
    sys.exit(1)
PY
