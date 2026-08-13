---
name: release-observe-rollback
description: After Gate VERIFIED, shadow-apply locally, rollback, and keep a local draft patch. Never merge or git push.
assign_when: quality-officer sees Kernel verdict VERIFIED and must request Controller release.
---

# release-observe-rollback

```bash
bash scripts/run.sh "$CASE_ID"
```

Principal: `agent:lead`. Kernel performs shadow apply + rollback + local draft patch. Never `git push`, never merge, never production deploy.
