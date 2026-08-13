---
name: attribute-skip
description: Record a Kernel investigation without a factorial experiment when the Issue already names insert/query file_id leakage.
assign_when: Attribution is on-demand and kotaemon #758 already states root cause.
---

# attribute-skip

```bash
bash scripts/run.sh "$CASE_ID"
```

Principal: `agent:attribution`. Do not invent Langfuse traces. Reply with Kernel JSON `conclusion`.
