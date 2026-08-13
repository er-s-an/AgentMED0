#!/usr/bin/env bash
# Fetch Langfuse traces via Kernel (Kernel holds keys). Never invent spans.
# Investigator/Attribution: POST EvidenceReceipt when missing.
# Verifier: eval/target only; print NEEDS_CONTEXT; do not POST evidence.
# Usage: scripts/run.sh $CASE_ID [investigator|attribution|verifier]
set -euo pipefail
KERNEL="${AGENTMED_KERNEL_URL:-http://host.docker.internal:8088}"
CASE_ID="${1:?case id required}"
ROLE="${2:-}"
if [ -z "$ROLE" ]; then
  case "${AGENTMED_PRINCIPAL:-}" in
    agent:attribution) ROLE=attribution ;;
    agent:verifier) ROLE=verifier ;;
    *) ROLE=investigator ;;
  esac
fi
case "$ROLE" in
  investigator|attribution|verifier) ;;
  *)
    echo "role must be investigator, attribution, or verifier (got: $ROLE)" >&2
    exit 1
    ;;
esac
if [ -z "${AGENTMED_PRINCIPAL:-}" ]; then
  PRINCIPAL="agent:$ROLE"
else
  PRINCIPAL="$AGENTMED_PRINCIPAL"
fi
python3 - "$KERNEL" "$PRINCIPAL" "$CASE_ID" "$ROLE" <<'PY'
import json, sys, urllib.error, urllib.parse, urllib.request

kernel, principal, case_id, role = sys.argv[1:]
write_receipt = role in {"investigator", "attribution"}


def missing_payload(reason, receipt=None):
    body = {
        "needs_context": True,
        "status": "NEEDS_CONTEXT",
        "role": role,
        "traces": [],
        "missing": ["target_app_langfuse_traces"],
        "reason": reason,
        "note": "Do not invent spans. Verifier must never see Builder chain-of-thought.",
    }
    if receipt is not None:
        body["receipt"] = receipt
    return body


def post_evidence(reason: str) -> dict:
    missing = ["target_app_langfuse_traces"]
    body = json.dumps(
        {
            "kind": "langfuse_traces",
            "summary": reason,
            "artifacts": [],
            "missing": missing,
        }
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
            receipt = json.loads(resp.read().decode() or "{}")
    except Exception as exc:
        receipt = {"kernel_post_error": str(exc), "missing": missing}
    return missing_payload(reason, receipt)


qs = urllib.parse.urlencode({"role": role})
url = f"{kernel}/v1/cases/{case_id}/langfuse-traces?{qs}"
req = urllib.request.Request(
    url,
    headers={"X-AgentMED-Principal": principal},
    method="GET",
)
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode() or "{}")
except urllib.error.HTTPError as exc:
    reason = f"Kernel langfuse-traces HTTP {exc.code}"
    print(json.dumps(post_evidence(reason) if write_receipt else missing_payload(reason), ensure_ascii=False))
    sys.exit(0)
except urllib.error.URLError as exc:
    reason = f"Kernel unreachable: {exc}"
    print(json.dumps(post_evidence(reason) if write_receipt else missing_payload(reason), ensure_ascii=False))
    sys.exit(0)

needs = bool(payload.get("needs_context"))
traces = payload.get("traces") or payload.get("spans") or []
if needs or not traces:
    reason = payload.get("summary") or payload.get("reason") or "Langfuse traces missing or empty; needs_context"
    print(json.dumps(post_evidence(reason) if write_receipt else missing_payload(reason), ensure_ascii=False))
    sys.exit(0)

print(json.dumps(payload, ensure_ascii=False))
PY
