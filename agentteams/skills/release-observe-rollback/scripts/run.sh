#!/usr/bin/env bash
# Request Kernel shadow apply + rollback drill as agent:lead. No production deploy.
# Stop if next is not SHADOW_DRILL (missing human Approval).
set -euo pipefail
KERNEL="${AGENTMED_KERNEL_URL:-http://host.docker.internal:8088}"
PRINCIPAL="${AGENTMED_PRINCIPAL:-agent:lead}"
CASE_ID="${1:?case id required}"
python3 - "$KERNEL" "$PRINCIPAL" "$CASE_ID" <<'PY'
import json, sys, urllib.error, urllib.request

kernel, principal, case_id = sys.argv[1:]
headers = {"X-AgentMED-Principal": principal}


def get(url):
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


try:
    nxt = get(f"{kernel}/v1/cases/{case_id}/next")
    actions = nxt.get("next") or []
    code = (actions[0] or {}).get("code") if actions else None
    if code != "SHADOW_DRILL":
        sys.stderr.write(
            "stop: next is not SHADOW_DRILL. Human must approve the WorkOrder first.\n"
            + json.dumps(nxt, ensure_ascii=False)
            + "\n"
        )
        sys.exit(2)
    req = urllib.request.Request(
        f"{kernel}/v1/cases/{case_id}/shadow",
        data=b"",
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        sys.stdout.write(resp.read().decode())
        sys.stdout.write("\n")
except urllib.error.HTTPError as exc:
    sys.stderr.write(f"Kernel error HTTP {exc.code} for shadow: {exc.read().decode() or exc.reason}\n")
    sys.exit(1)
except urllib.error.URLError as exc:
    sys.stderr.write(f"Kernel unreachable for shadow: {exc}\n")
    sys.exit(1)
PY
