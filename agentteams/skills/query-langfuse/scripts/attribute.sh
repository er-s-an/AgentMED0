#!/usr/bin/env bash
# Thin alias: attribution belongs in attribute-skip, not in this skill.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ALT="$HERE/../../attribute-skip/scripts/run.sh"
if [ -x "$ALT" ]; then
  exec "$ALT" "$@"
fi
echo "query-langfuse/scripts/attribute.sh is an alias. Run attribute-skip/scripts/run.sh \"\$CASE_ID\"." >&2
exit 1
