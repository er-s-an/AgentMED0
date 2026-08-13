---
name: curate-regression-asset
description: Close the Case with a RegressionAsset after rollback. Run scripts/run.sh.
assign_when: Case has Gate evidence and Curator must persist a reusable asset.
---

# curate-regression-asset

```bash
bash scripts/run.sh "$CASE_ID"
```

Principal: `agent:curator`. Reply with Kernel `id` of the regression asset. Do not rewrite history.
