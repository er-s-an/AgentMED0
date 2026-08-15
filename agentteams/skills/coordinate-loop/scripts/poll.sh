#!/usr/bin/env bash
# Team Leader: poll Kernel Case state and the next legal step. Chat is not source of truth.
set -euo pipefail
KERNEL="${AGENTMED_KERNEL_URL:-http://host.docker.internal:8088}"
PRINCIPAL="${AGENTMED_PRINCIPAL:-agent:lead}"
python3 - "$KERNEL" "$PRINCIPAL" "$@" <<'PY'
import json, sys, urllib.error, urllib.parse, urllib.request

kernel, principal, *args = sys.argv[1:]
headers = {"X-AgentMED-Principal": principal}


def get(url):
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


try:
    if args and args[0] == "--case":
        if len(args) < 2:
            sys.stderr.write("case id required after --case\n")
            sys.exit(1)
        case_id = args[1]
        case = get(f"{kernel}/v1/cases/{case_id}")
    else:
        if not args:
            sys.stderr.write("github issue url or --case <id> required\n")
            sys.exit(1)
        qs = urllib.parse.urlencode({"source_ref": args[0]})
        listed = get(f"{kernel}/v1/cases?{qs}")
        cases = listed.get("cases") or []
        if not cases:
            sys.stdout.write(json.dumps(listed, ensure_ascii=False) + "\n")
            raise SystemExit(0)
        case = cases[0]
        case_id = case["id"]
    nxt = get(f"{kernel}/v1/cases/{case_id}/next")
    payload = {
        "case": case,
        "case_id": case_id,
        "state": nxt.get("state") or case.get("state"),
        "next": nxt.get("next") or [],
        "workload": nxt.get("workload"),
    }
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.write("\n")
except urllib.error.HTTPError as exc:
    sys.stderr.write(f"Kernel error HTTP {exc.code} for poll: {exc.read().decode() or exc.reason}\n")
    sys.exit(1)
except urllib.error.URLError as exc:
    sys.stderr.write(f"Kernel unreachable for poll: {exc}\n")
    sys.exit(1)
PY
