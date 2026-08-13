#!/usr/bin/env bash
# Fetch Langfuse traces via Kernel (Kernel holds keys). Never invent spans.
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
# Verifier must only receive eval/target traces — Kernel filters by role=.
python3 - "$KERNEL" "$PRINCIPAL" "$CASE_ID" "$ROLE" <<'PY'
import json, sys, urllib.error, urllib.parse, urllib.request

kernel, principal, case_id, role = sys.argv[1:]


def post_missing(reason: str) -> dict:
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
    return {
        "needs_context": True,
        "role": role,
        "traces": [],
        "missing": missing,
        "receipt": receipt,
        "note": "Do not invent spans. Verifier must never see Builder chain-of-thought.",
    }


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
    print(json.dumps(post_missing(f"Kernel langfuse-traces HTTP {exc.code}"), ensure_ascii=False))
    sys.exit(0)
except urllib.error.URLError as exc:
    print(json.dumps(post_missing(f"Kernel unreachable: {exc}"), ensure_ascii=False))
    sys.exit(0)

needs = bool(payload.get("needs_context"))
traces = payload.get("traces") or payload.get("spans") or []
if needs or not traces:
    print(
        json.dumps(
            post_missing(payload.get("summary") or "Langfuse traces missing or empty; needs_context"),
            ensure_ascii=False,
        )
    )
    sys.exit(0)

print(json.dumps(payload, ensure_ascii=False))
PY
echo
