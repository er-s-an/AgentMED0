#!/usr/bin/env bash
# Generic enterprise-monitor entry. Never Aliyun CMS. MCP is the extension point.
# Cannot connect → POST EvidenceReceipt with missing. Never forge metrics.
# Degrade always exits 0 so the Case can continue (kotaemon #758 default).
set -euo pipefail
KERNEL="${AGENTMED_KERNEL_URL:-http://host.docker.internal:8088}"
PRINCIPAL="${AGENTMED_PRINCIPAL:-agent:investigator}"
CASE_ID="${1:?case id required}"
MONITOR_URL="${MONITOR_URL:-}"
MONITOR_MCP_URL="${MONITOR_MCP_URL:-}"
python3 - "$KERNEL" "$PRINCIPAL" "$CASE_ID" "$MONITOR_URL" "$MONITOR_MCP_URL" <<'PY'
import json, sys, urllib.error, urllib.request

kernel, principal, case_id, monitor_url, mcp_url = sys.argv[1:]


def probe(url: str) -> bool:
    if not url:
        return False
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return 200 <= resp.status < 400
    except Exception:
        return False


def post_evidence(kind: str, summary: str, artifacts: list, missing: list) -> dict:
    body = json.dumps(
        {"kind": kind, "summary": summary, "artifacts": artifacts, "missing": missing}
    ).encode()
    req = urllib.request.Request(
        f"{kernel}/v1/cases/{case_id}/evidence",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-AgentMED-Principal": principal,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode() or "{}")
    except Exception as exc:
        return {
            "needs_context": True,
            "integrity": "partial",
            "missing": missing,
            "kernel_post_error": str(exc),
        }


reachable_http = probe(monitor_url)
reachable_mcp = probe(mcp_url)

if not monitor_url and not mcp_url:
    receipt = post_evidence(
        "enterprise_monitor",
        "No enterprise monitor station configured (kotaemon #758 default path).",
        [],
        ["enterprise_monitor_station"],
    )
    out = {
        "status": "degraded",
        "reason": "no_station_configured",
        "receipt": receipt,
        "missing": receipt.get("missing") or ["enterprise_monitor_station"],
    }
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(0)

if not reachable_http and not reachable_mcp:
    missing = ["enterprise_monitor_station"]
    receipt = post_evidence(
        "enterprise_monitor",
        "Configured MONITOR_URL/MCP unreachable. No metrics recorded. Do not operate Aliyun CMS from this skill.",
        [],
        missing,
    )
    print(
        json.dumps(
            {
                "status": "degraded",
                "reason": "station_unreachable",
                "receipt": receipt,
                "missing": missing,
            },
            ensure_ascii=False,
        )
    )
    sys.exit(0)

# Reachable station is not a license to invent numbers. Metrics stay missing until MCP query exists.
missing = ["enterprise_monitor_metrics"]
receipt = post_evidence(
    "enterprise_monitor",
    "Monitor or MCP endpoint reachable; no metric values queried (MCP is the extension point).",
    [
        {
            "type": "monitor_health",
            "http_ref": "MONITOR_URL" if reachable_http else None,
            "mcp_ref": "MONITOR_MCP_URL" if reachable_mcp else None,
            "status": "reachable",
        }
    ],
    missing,
)
print(
    json.dumps(
        {
            "status": "connected_no_metrics",
            "receipt": receipt,
            "missing": missing,
        },
        ensure_ascii=False,
    )
)
PY
echo
