#!/usr/bin/env bash
# Team Leader: poll Kernel Case state. Chat is not source of truth.
set -euo pipefail
KERNEL="${AGENTMED_KERNEL_URL:-http://host.docker.internal:8088}"
PRINCIPAL="${AGENTMED_PRINCIPAL:-agent:lead}"
python3 - "$KERNEL" "$PRINCIPAL" "$@" <<'PY'
import sys, urllib.error, urllib.parse, urllib.request

kernel, principal, *args = sys.argv[1:]
headers = {"X-AgentMED-Principal": principal}
if args and args[0] == "--case":
    if len(args) < 2:
        sys.stderr.write("case id required after --case\n")
        sys.exit(1)
    url = f"{kernel}/v1/cases/{args[1]}"
else:
    if not args:
        sys.stderr.write("github issue url or --case <id> required\n")
        sys.exit(1)
    qs = urllib.parse.urlencode({"source_ref": args[0]})
    url = f"{kernel}/v1/cases?{qs}"
req = urllib.request.Request(url, headers=headers, method="GET")
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        sys.stdout.write(resp.read().decode())
        sys.stdout.write("\n")
except urllib.error.HTTPError as exc:
    sys.stderr.write(f"Kernel error HTTP {exc.code} for poll: {exc.read().decode() or exc.reason}\n")
    sys.exit(1)
except urllib.error.URLError as exc:
    sys.stderr.write(f"Kernel unreachable for poll: {exc}\n")
    sys.exit(1)
PY
