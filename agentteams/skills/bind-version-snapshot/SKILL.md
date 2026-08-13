---
name: bind-version-snapshot
description: Freeze VersionSnapshot + evidence on a Case by running scripts/run.sh. Execute the script; do not invent a commit.
assign_when: AcceptanceSpec is confirmed (Kernel state investigating) and Investigator must bind the kotaemon snapshot.
---

# bind-version-snapshot

```bash
bash scripts/run.sh "$CASE_ID"
```

Principal: `agent:investigator`. Kernel: `http://host.docker.internal:8088`.

For kotaemon #758 the Kernel binds repo Cinnamon/kotaemon commit `ffe766f24d4ef8a91f8c61871d2b5a1930aa204e`. Do not invent SHAs.

Reply with the JSON `snapshot.id`. Do not patch. Do not call verify.
