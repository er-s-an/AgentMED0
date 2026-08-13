#!/usr/bin/env bash
# Team Leader poll helper (Kernel is source of truth). Same as poll.sh.
set -euo pipefail
exec "$(cd "$(dirname "$0")" && pwd)/poll.sh" "$@"
