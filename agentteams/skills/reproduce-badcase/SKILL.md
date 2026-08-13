---
name: reproduce-badcase
description: For kotaemon #758, run bind-version-snapshot/scripts/run.sh. Gate later proves the bad case. Do not fake a pass.
assign_when: Investigator must record that the scoped-file failure is real.
---

# reproduce-badcase

MVP: Kernel investigate already records the issue evidence. Run:

```bash
bash ../bind-version-snapshot/scripts/run.sh "$CASE_ID"
```

If that already ran, `bash scripts/run.sh "$CASE_ID"` (same Kernel call; Kernel is idempotent enough to error if repeated — then GET `/v1/cases/$CASE_ID` and report state).

Never mark reproduced without Kernel JSON.
