#!/usr/bin/env bash
# Intake: POST Kernel /v1/signals/ingest-langfuse (low-score / failed eval → Signal).
# Empty result → needs_context. Never invent a GitHub issue.
set -euo pipefail
KERNEL="${AGENTMED_KERNEL_URL:-http://host.docker.internal:8088}"
PRINCIPAL="${AGENTMED_PRINCIPAL:-agent:intake}"
BODY="${1:-{}}"
python3 - "$KERNEL" "$PRINCIPAL" "$BODY" <<'PY'
import json, sys, urllib.error, urllib.request

kernel, principal, raw = sys.argv[1:]
try:
    payload = json.loads(raw) if raw.strip() else {}
except json.JSONDecodeError:
    payload = {}
body = json.dumps(payload).encode()
req = urllib.request.Request(
    f"{kernel}/v1/signals/ingest-langfuse",
    data=body,
    headers={
        "Content-Type": "application/json",
        "X-AgentMED-Principal": principal,
    },
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=60) as resp:
        text = resp.read().decode() or "{}"
        data = json.loads(text)
except urllib.error.HTTPError as exc:
    detail = exc.read().decode() or exc.reason
    print(
        json.dumps(
            {
                "needs_context": True,
                "status": "NEEDS_CONTEXT",
                "reason": f"ingest-langfuse HTTP {exc.code}",
                "detail": detail[:2000],
            },
            ensure_ascii=False,
        )
    )
    sys.exit(0)
except urllib.error.URLError as exc:
    print(
        json.dumps(
            {
                "needs_context": True,
                "status": "NEEDS_CONTEXT",
                "reason": f"Kernel unreachable: {exc}",
            },
            ensure_ascii=False,
        )
    )
    sys.exit(0)

signals = data.get("signals") or data.get("signal")
cases = data.get("cases") or data.get("case")
empty_list = isinstance(signals, list) and not signals
no_signal = signals in (None, {}, [])
if data.get("needs_context") or empty_list or (no_signal and not cases):
    print(
        json.dumps(
            {
                "needs_context": True,
                "status": "NEEDS_CONTEXT",
                "reason": "no low-score/failed Langfuse eval to ingest; not inventing an issue",
                "kernel": data,
            },
            ensure_ascii=False,
        )
    )
    sys.exit(0)

print(json.dumps(data, ensure_ascii=False))
PY
echo
