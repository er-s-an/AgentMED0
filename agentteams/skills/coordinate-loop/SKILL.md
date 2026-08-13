---
name: coordinate-loop
description: Drive one AgentMED Case as Team Leader. Dispatch Kernel-legal Worker tasks in order. Poll Kernel after every step. Do not ask the admin.
assign_when: Manager hands a GitHub signal or pending Case to quality-officer.
---

# coordinate-loop

You are Team Leader. YOLO: do not ask the admin. Kernel HTTP is source of truth: `http://host.docker.internal:8088`.

Matrix IDs use domain `matrix-local.agentteams.io:18080`. @mention with the **full** ID.

Poll:

```bash
bash scripts/poll.sh "$GITHUB_URL"
# later:
bash scripts/poll.sh --case "$CASE_ID"
```

## Sequence (serial)

1. @intake: run `ingest-signal/scripts/run.sh <github-url>`. Wait until `GET /v1/cases?source_ref=` returns a Case.
2. Wait until Kernel `state=investigating` (human CLI confirms AcceptanceSpec). Do not skip.
3. @investigator: `bind-version-snapshot/scripts/run.sh $CASE_ID`.
4. @attribution: `attribute-skip/scripts/run.sh $CASE_ID`.
5. @builder: `propose-candidate` skill (write lightrag_store.py, then submit). Never forward Builder CoT to Verifier.
6. @verifier: `independent-verify/scripts/run.sh $CASE_ID`. Isolated. No Builder files except Kernel verifier-context.
7. If REJECTED: @builder again with GateReport only; never patch a sealed candidate.
8. If VERIFIED: you run `release-observe-rollback/scripts/run.sh $CASE_ID`.
9. @curator: `curate-regression-asset/scripts/run.sh $CASE_ID`.

After every step: poll Kernel. Do not trust chat. Do not run ingest/investigate/candidates/verify/close yourself.

Forbidden: Gate override, merge, push, production deploy, serving as Verifier, proposing candidates.
