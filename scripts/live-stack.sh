#!/usr/bin/env bash
# Bring up the live AgentMED stack: Langfuse + Kernel API + AgentTeams (Step Plan).
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
  echo "Docker daemon is not ready. Open Docker Desktop and retry." >&2
  exit 1
fi

KEY="${STEP_API_KEY:-${OPENAI_API_KEY:-}}"
BASE_URL="${OPENAI_BASE_URL:-https://api.stepfun.com/step_plan/v1}"
MODEL="${AGENTMED_MODEL:-step-3.7-flash}"

if [[ -z "$KEY" ]]; then
  echo "Set STEP_API_KEY (Step Plan key from https://platform.stepfun.com/interface-key)." >&2
  echo "Base URL must be ${BASE_URL}  model=${MODEL}" >&2
  exit 1
fi

echo "==> Langfuse"
docker compose -f "$HOME/langfuse/docker-compose.yml" up -d
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

echo "==> AgentTeams (openai-compat → Step Plan)"
export AGENTTEAMS_NON_INTERACTIVE=1
export AGENTTEAMS_VERSION="${AGENTTEAMS_VERSION:-v1.2.2}"
export AGENTTEAMS_LLM_PROVIDER=openai-compat
export AGENTTEAMS_OPENAI_BASE_URL="$BASE_URL"
export AGENTTEAMS_DEFAULT_MODEL="$MODEL"
export AGENTTEAMS_LLM_API_KEY="$KEY"
export AGENTTEAMS_EMBEDDING_MODEL="${AGENTTEAMS_EMBEDDING_MODEL-}"
export AGENTTEAMS_ADMIN_PASSWORD="${AGENTTEAMS_ADMIN_PASSWORD:-agentmed-admin}"
export AGENTTEAMS_DASHBOARD=1
export AGENTTEAMS_MANAGER_RUNTIME="${AGENTTEAMS_MANAGER_RUNTIME:-copaw}"
export AGENTTEAMS_DEFAULT_WORKER_RUNTIME="${AGENTTEAMS_DEFAULT_WORKER_RUNTIME:-copaw}"
export AGENTTEAMS_MODEL_CONTEXT_WINDOW="${AGENTTEAMS_MODEL_CONTEXT_WINDOW:-128000}"
export AGENTTEAMS_MODEL_MAX_TOKENS="${AGENTTEAMS_MODEL_MAX_TOKENS:-16384}"
export AGENTTEAMS_MODEL_REASONING="${AGENTTEAMS_MODEL_REASONING:-true}"
export AGENTTEAMS_MODEL_VISION="${AGENTTEAMS_MODEL_VISION:-false}"
bash <(curl -fsSL https://raw.githubusercontent.com/agentscope-ai/AgentTeams/main/install/agentteams-install.sh)

echo "==> Apply AgentMED workers / team / skills"
"$ROOT/.venv/bin/agentmed" apply-agentteams

echo
echo "Langfuse UI:     http://localhost:3001  (admin@example.com / changeme123)"
echo "Element Web:     http://127.0.0.1:18088"
echo "Higress gateway: http://127.0.0.1:18080"
echo "Dashboard:       http://127.0.0.1:13000"
echo "Kernel API:      run  agentmed serve"
echo "Then: agentmed doctor && agentmed run --signal https://github.com/Cinnamon/kotaemon/issues/758 --accept"
