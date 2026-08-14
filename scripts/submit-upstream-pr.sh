#!/usr/bin/env bash
# Open the kotaemon #758 PR. Kernel and AgentTeams must never call this.
# A human has to pass --i-am-human.
set -euo pipefail

I_AM_HUMAN=0
DRY_RUN=0
PACK=""
REPO_DIR=""

usage() {
  cat <<'EOF'
Usage:
  ./scripts/submit-upstream-pr.sh --i-am-human --pack <pack-dir> [--dry-run] [--repo-dir <kotaemon-checkout>]

Refuses without --i-am-human. Does not run from AgentTeams skills.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --i-am-human) I_AM_HUMAN=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --pack) PACK="${2:-}"; shift 2 ;;
    --pack=*) PACK="${1#*=}"; shift ;;
    --repo-dir) REPO_DIR="${2:-}"; shift 2 ;;
    --repo-dir=*) REPO_DIR="${1#*=}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

if [[ "$I_AM_HUMAN" != "1" ]]; then
  echo "AgentMED will not open an upstream PR. A human must pass --i-am-human." >&2
  exit 2
fi

if [[ -z "$PACK" ]]; then
  echo "--pack <dir> is required" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"
if [[ -n "${PYTHON:-}" ]]; then
  PY="$PYTHON"
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
else
  PY="python3"
fi
ARGS=(--i-am-human --pack "$PACK")
if [[ "$DRY_RUN" == "1" ]]; then
  ARGS+=(--dry-run)
fi
if [[ -n "$REPO_DIR" ]]; then
  ARGS+=(--repo-dir "$REPO_DIR")
fi
exec "$PY" -m agentmed.prpack "${ARGS[@]}"
