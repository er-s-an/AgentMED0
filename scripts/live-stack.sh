#!/usr/bin/env bash
# Optional live infra for contributors: Langfuse + AgentTeams.
# Kernel is this repo: run `agentmed serve` after this script.
set -euo pipefail
export PATH="/usr/local/bin:/Applications/Docker.app/Contents/Resources/bin:$PATH"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon is not ready. Start Docker and retry." >&2
  exit 1
fi

KEY="${STEP_API_KEY:-${OPENAI_API_KEY:-}}"
BASE_URL="${OPENAI_BASE_URL:-https://api.stepfun.com/step_plan/v1}"
MODEL="${AGENTMED_MODEL:-step-3.7-flash}"

if [[ -z "$KEY" ]]; then
  echo "Set STEP_API_KEY in .env (copy .env.example). Model host: ${BASE_URL}  model=${MODEL}" >&2
  exit 1
fi

LANGFUSE_COMPOSE="${LANGFUSE_COMPOSE:-$HOME/langfuse/docker-compose.yml}"
if [[ ! -f "$LANGFUSE_COMPOSE" ]]; then
  echo "Langfuse compose not found: ${LANGFUSE_COMPOSE}" >&2
  echo "Clone https://github.com/langfuse/langfuse (self-host compose) and set LANGFUSE_COMPOSE, or place it at ~/langfuse/docker-compose.yml." >&2
  exit 1
fi

echo "==> Langfuse (${LANGFUSE_COMPOSE})"
docker compose -f "$LANGFUSE_COMPOSE" up -d
for _ in $(seq 1 40); do
  if curl -sf http://localhost:3001/api/public/health >/dev/null; then
    break
  fi
  sleep 2
done
curl -sf http://localhost:3001/api/public/health >/dev/null || {
  echo "Langfuse did not become healthy on http://localhost:3001" >&2
  exit 1
}

if [[ "$(uname -s)" == "Linux" ]] && ! getent hosts host.docker.internal >/dev/null 2>&1; then
  echo "note: Linux has no host.docker.internal by default; AgentTeams workers need extra_hosts host-gateway to reach Kernel :8088." >&2
fi

KERNEL_PORT="${KERNEL_API_PORT:-8088}"
PROXY_URL="http://host.docker.internal:${KERNEL_PORT}/v1"

echo "==> AgentTeams (OpenAI-compat base URL → Kernel :${KERNEL_PORT})"
export AGENTTEAMS_NON_INTERACTIVE=1
export AGENTTEAMS_VERSION="${AGENTTEAMS_VERSION:-v1.2.2}"
export AGENTTEAMS_LLM_PROVIDER=openai-compat
export AGENTTEAMS_OPENAI_BASE_URL="$PROXY_URL"
export AGENTTEAMS_DEFAULT_MODEL="$MODEL"
export AGENTTEAMS_LLM_API_KEY="${AGENTTEAMS_LLM_API_KEY:-agentmed-kernel-proxy}"
export AGENTTEAMS_EMBEDDING_MODEL="${AGENTTEAMS_EMBEDDING_MODEL-}"
export AGENTTEAMS_ADMIN_PASSWORD="${AGENTTEAMS_ADMIN_PASSWORD:-agentmed-admin}"
export AGENTTEAMS_DASHBOARD=1
export AGENTTEAMS_MANAGER_RUNTIME="${AGENTTEAMS_MANAGER_RUNTIME:-copaw}"
export AGENTTEAMS_DEFAULT_WORKER_RUNTIME="${AGENTTEAMS_DEFAULT_WORKER_RUNTIME:-copaw}"
export AGENTTEAMS_MODEL_CONTEXT_WINDOW="${AGENTTEAMS_MODEL_CONTEXT_WINDOW:-128000}"
export AGENTTEAMS_MODEL_MAX_TOKENS="${AGENTTEAMS_MODEL_MAX_TOKENS:-16384}"
export AGENTTEAMS_MODEL_REASONING="${AGENTTEAMS_MODEL_REASONING:-true}"
export AGENTTEAMS_MODEL_VISION="${AGENTTEAMS_MODEL_VISION:-false}"
export AGENTMED_RETARGET_LLM=1
bash <(curl -fsSL https://raw.githubusercontent.com/agentscope-ai/AgentTeams/main/install/agentteams-install.sh)

echo "==> Apply AgentMED workers / team / skills"
if [[ -x "$ROOT/.venv/bin/agentmed" ]]; then
  "$ROOT/.venv/bin/agentmed" apply-agentteams
else
  echo "Install the package first: pip install -e '.[dev]'" >&2
  exit 1
fi

echo
echo "Langfuse UI:     http://localhost:3001"
echo "Element Web:     http://127.0.0.1:18088"
echo "Higress gateway: http://127.0.0.1:18080"
echo "Dashboard:       http://127.0.0.1:13000"
echo "Kernel:          agentmed serve   # :${KERNEL_PORT}"
echo "Then: agentmed doctor && agentmed run --signal https://github.com/Cinnamon/kotaemon/issues/758 --accept-adapter-defaults"
