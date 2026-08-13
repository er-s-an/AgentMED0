---
name: query-langfuse
description: Read Langfuse if reachable; otherwise declare missing and continue. Never forge spans. For #758 attribution prefer attribute-skip.
assign_when: Investigator, Attribution, or Verifier wants traces and must not invent them.
---

# query-langfuse

From Docker, Langfuse is `http://host.docker.internal:3001`. If curl fails or returns empty, write `missing: target_app_langfuse_traces` and continue.

For kotaemon #758 Attribution: run `attribute-skip/scripts/run.sh "$CASE_ID"` instead of a factorial study.

Never copy Builder chain-of-thought to Verifier.
