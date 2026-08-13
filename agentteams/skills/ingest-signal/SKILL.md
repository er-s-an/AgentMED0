---
name: ingest-signal
description: Open a Kernel Signal+Case from a GitHub issue URL by running scripts/run.sh. Do not describe the HTTP call; execute it.
assign_when: A GitHub issue URL arrives and Intake must open or reuse a Case.
---

# ingest-signal

Kernel is source of truth. Matrix chat is not.

## Do this

```bash
bash /root/.copaw-worker/intake/skills/ingest-signal/scripts/run.sh \
  "https://github.com/Cinnamon/kotaemon/issues/758"
```

If `scripts/run.sh` is next to this file:

```bash
bash "$(dirname "$0")/scripts/run.sh" "$GITHUB_ISSUE_URL"
```

or from this skill directory: `bash scripts/run.sh "$GITHUB_ISSUE_URL"`.

Principal: `agent:intake`. Kernel: `http://host.docker.internal:8088`.

## Done when

The script prints JSON with `case.id` and `case.state` (usually `awaiting_acceptance`). Reply to the Team Leader with that `case.id` only. Do not patch code. Do not verify.
