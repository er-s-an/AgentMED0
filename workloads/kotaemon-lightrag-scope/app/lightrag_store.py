"""Faithful reproduction of kotaemon LightRAG file-scoping bug.

Upstream issue: https://github.com/Cinnamon/kotaemon/issues/758
Upstream commit: ffe766f24d4ef8a91f8c61871d2b5a1930aa204e

In kotaemon's LightRAGIndexingPipeline.call_graphrag_index, documents are
inserted with `graphrag_func.insert(combined_doc)` and the file id is not
passed. LightRAGRetrieverPipeline then looks up a collection-wide graph and
queries it without scoping to the selected file_ids. Selecting file A still
returns content from file B.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LightRAGStore:
    chunks: list[dict[str, str | None]] = field(default_factory=list)

    def insert(self, text: str, file_id: str | None = None) -> None:
        # BUG: file_id is ignored, matching kotaemon insert without file id.
        del file_id
        self.chunks.append({"text": text, "file_id": None})

    def query(self, text: str, file_ids: list[str] | None = None) -> list[str]:
        del text
        if not file_ids:
            return []
        # BUG: selected file_ids only gate "index exists", they do not filter.
        return [str(chunk["text"]) for chunk in self.chunks]
