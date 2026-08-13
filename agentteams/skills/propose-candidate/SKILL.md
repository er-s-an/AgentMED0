---
name: propose-candidate
description: Fetch builder-context, write a full lightrag_store.py that scopes chunks by file_id, then submit with scripts/run.sh. Do not self-verify.
assign_when: Case is proposing and only agent:builder may emit a candidate.
---

# propose-candidate

Kernel: `http://host.docker.internal:8088`. Principal: `agent:builder`.

## Steps

1. Fetch context (prints buggy source + AcceptanceSpec):

```bash
bash scripts/run.sh "$CASE_ID"
```

2. Write `/tmp/lightrag_store.py` as a **complete file**. Required behavior:

- `insert(text, file_id=None)` **must store** `file_id` on the chunk (do not `del file_id`).
- `query(text, file_ids=None)` if `file_ids` is `None` or `[]` → return `[]`.
- otherwise return only chunks whose `file_id` is in `file_ids`.

Reference shape (you may write this):

```python
from dataclasses import dataclass, field

@dataclass
class LightRAGStore:
    chunks: list[dict[str, str | None]] = field(default_factory=list)

    def insert(self, text: str, file_id: str | None = None) -> None:
        self.chunks.append({"text": text, "file_id": file_id})

    def query(self, text: str, file_ids: list[str] | None = None) -> list[str]:
        del text
        if not file_ids:
            return []
        selected = set(file_ids)
        return [str(chunk["text"]) for chunk in self.chunks if chunk.get("file_id") in selected]
```

3. Submit:

```bash
bash scripts/run.sh "$CASE_ID" /tmp/lightrag_store.py "persist file_id and filter query"
```

## Forbidden

Do not run pytest. Do not call `/verify`. Do not read eval/. Do not announce VERIFIED.
