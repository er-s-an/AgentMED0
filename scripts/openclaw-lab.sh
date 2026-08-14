#!/usr/bin/env bash
# Wire a local OpenClaw lab to AgentMED's StepFun key and Langfuse.
# Secrets stay in ~/.openclaw/.env (gitignored). This script never prints them.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

KEY="${STEPFUN_API_KEY:-${STEP_API_KEY:-${OPENAI_API_KEY:-}}}"
if [[ -z "$KEY" ]]; then
  echo "Set STEP_API_KEY in AgentMED .env first. Do not paste the key into chat." >&2
  exit 1
fi

STATE="${OPENCLAW_STATE_DIR:-$HOME/.openclaw}"
mkdir -p "$STATE"
ENV_FILE="$STATE/.env"
CFG="$STATE/openclaw.json"
KERNEL_URL="http://127.0.0.1:${KERNEL_API_PORT:-8088}/v1"
LANGFUSE_URL="${LANGFUSE_HOST:-http://localhost:3001}"
MODEL="${AGENTMED_MODEL:-step-3.7-flash}"

python3 - "$ENV_FILE" "$KEY" "$LANGFUSE_URL" "${LANGFUSE_PUBLIC_KEY:-}" "${LANGFUSE_SECRET_KEY:-}" <<'PY'
from pathlib import Path
import sys

path, key, langfuse, pub, sec = sys.argv[1:6]
existing: dict[str, str] = {}
p = Path(path)
if p.exists():
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        existing[name] = value
existing["STEPFUN_API_KEY"] = key
existing["STEP_API_KEY"] = key
existing["LANGFUSE_HOST"] = langfuse
existing["LANGFUSE_BASE_URL"] = langfuse
if pub:
    existing["LANGFUSE_PUBLIC_KEY"] = pub
if sec:
    existing["LANGFUSE_SECRET_KEY"] = sec
# Do not copy the StepFun key onto OPENAI_API_KEY — that would hit api.openai.com.
lines = [f"{name}={existing[name]}" for name in existing]
p.write_text("\n".join(lines) + "\n", encoding="utf-8")
p.chmod(0o600)
print(f"wrote {p} keys={sorted(existing)} values_redacted")
PY

python3 - "$CFG" "$KERNEL_URL" "$MODEL" <<'PY'
import json
from pathlib import Path
import sys

path, kernel, model = sys.argv[1:4]
cfg = {
    "agents": {"defaults": {"model": {"primary": f"agentmed/{model}"}}},
    "models": {
        "mode": "merge",
        "providers": {
            "agentmed": {
                "baseUrl": kernel,
                "api": "openai-completions",
                "apiKey": "agentmed-kernel-proxy",
                "request": {"allowPrivateNetwork": True},
                "models": [
                    {
                        "id": model,
                        "name": f"{model} via AgentMED Kernel",
                        "reasoning": True,
                        "contextWindow": 128000,
                        "maxTokens": 16384,
                    }
                ],
            }
        },
    },
    "plugins": {
        "allow": ["langfuse-bridge"],
        "entries": {"langfuse-bridge": {"enabled": True}},
    },
}
Path(path).write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
print(f"wrote {path} provider=agentmed model={model} kernel={kernel}")
PY

echo "Langfuse refs: host=${LANGFUSE_URL} public_key_ref=env:LANGFUSE_PUBLIC_KEY"
if curl -sf "${LANGFUSE_URL}/api/public/health" >/dev/null; then
  echo "Langfuse health: ok"
else
  echo "Langfuse health: down (OpenClaw can still run; Investigator will get NEEDS_CONTEXT)"
fi
if curl -sf "http://127.0.0.1:${KERNEL_API_PORT:-8088}/v1/models" >/dev/null; then
  echo "Kernel LLM proxy: ok"
else
  echo "Kernel LLM proxy: down. Start AgentMED serve so OpenClaw can use the StepFun key without holding it."
fi

if ! command -v openclaw >/dev/null 2>&1; then
  echo "openclaw CLI not on PATH. Install without onboarding:"
  echo "  curl -fsSL https://openclaw.ai/install.sh | bash -s -- --no-onboard"
  echo "This machine has Node $(node -v 2>/dev/null || echo missing); OpenClaw wants Node 22+."
  exit 0
fi

openclaw --version
openclaw doctor || true
echo "Next: openclaw gateway run   # LLM goes Kernel → StepFun; traces go Langfuse"
