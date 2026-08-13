---
name: independent-verify
description: Run Gate on the sealed candidate via scripts/run.sh. Never patch. Never rewrite REJECT as pass.
assign_when: A CandidateRevision is sealed and agent:verifier must score it without Builder context.
---

# independent-verify

```bash
bash scripts/run.sh "$CASE_ID"
```

Principal: `agent:verifier`. Kernel runs pytest. Reply with `verdict` from the JSON (`VERIFIED` or `REJECTED`).

Forbidden: editing candidate files, calling `/candidates`, sharing a room with Builder, overriding FAIL.
