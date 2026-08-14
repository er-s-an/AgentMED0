"""Map the Gate-verified file_id contract onto kotaemon's real LightRAG pipeline.

Gate verifies `lightrag_store.py`. This module rewrites the pinned
`lightrag_pipelines.py` at the two call sites named in
https://github.com/Cinnamon/kotaemon/issues/758
"""

from __future__ import annotations

from pathlib import Path

from agentmed.workloads.base import unified_files_diff

REPO_ROOT = Path(__file__).resolve().parents[3]
UPSTREAM_DIR = REPO_ROOT / "workloads" / "kotaemon-lightrag-scope" / "upstream"
BASE_FILE = UPSTREAM_DIR / "lightrag_pipelines.base.py"
UPSTREAM_PATH = "libs/ktem/ktem/index/file/graph/lightrag_pipelines.py"
BASE_COMMIT = "ffe766f24d4ef8a91f8c61871d2b5a1930aa204e"
ISSUE_URL = "https://github.com/Cinnamon/kotaemon/issues/758"
REPO = "https://github.com/Cinnamon/kotaemon"

_HELPERS = '''
def text_unit_file_id(unit: dict) -> str:
    """Best-effort file identity from a LightRAG text unit."""
    if not isinstance(unit, dict):
        return ""
    for key in ("file_path", "file_name", "full_doc_id", "doc_id", "source"):
        value = unit.get(key)
        if value:
            return str(value)
    return ""


def text_unit_matches_file_ids(unit: dict, selected: set[str]) -> bool:
    file_id = text_unit_file_id(unit)
    if not file_id:
        return False
    return file_id in selected or any(
        file_id.endswith(str(fid)) or str(fid) in file_id for fid in selected
    )


'''

_REPLACEMENTS = (
    (
        """        all_docs = [
            doc.text
            for doc in docs
            if doc.metadata.get("type", "text") == "text" and len(doc.text.strip()) > 0
        ]
""",
        """        all_docs = [
            (
                doc.text,
                str(
                    doc.metadata.get("file_id")
                    or doc.metadata.get("file_name")
                    or ""
                )
                or None,
            )
            for doc in docs
            if doc.metadata.get("type", "text") == "text" and len(doc.text.strip()) > 0
        ]
""",
    ),
    (
        """        for doc_id in range(0, len(all_docs), self.index_batch_size):
            cur_docs = all_docs[doc_id : doc_id + self.index_batch_size]
            combined_doc = "\\n".join(cur_docs)

            # Use insert for incremental updates
            graphrag_func.insert(combined_doc)
""",
        """        for doc_id in range(0, len(all_docs), self.index_batch_size):
            batch = all_docs[doc_id : doc_id + self.index_batch_size]
            cur_docs = [text for text, _file_id in batch]
            cur_ids = [file_id for _text, file_id in batch if file_id]
            combined_doc = "\\n".join(cur_docs)

            # #758: pass file ids so selected-file search can stay scoped.
            insert_kwargs = {}
            if cur_ids and len(cur_ids) == len(cur_docs):
                insert_kwargs["ids"] = cur_ids
                insert_kwargs["file_paths"] = cur_ids
            try:
                graphrag_func.insert(
                    cur_docs if insert_kwargs else combined_doc, **insert_kwargs
                )
            except TypeError:
                # Older LightRAG only accepted a single text blob.
                graphrag_func.insert(combined_doc)
""",
    ),
    (
        """async def lightrag_build_local_query_context(
    graph_func,
    query,
    query_param,
):
""",
        """async def lightrag_build_local_query_context(
    graph_func,
    query,
    query_param,
    file_ids=None,
):
""",
    ),
    (
        """    text_units_section_list = [["id", "content"]]
    for i, t in enumerate(use_text_units):
        text_units_section_list.append([str(i), t["content"]])
    sources_df = list_of_list_to_df(text_units_section_list)
""",
        """    selected = {str(fid) for fid in (file_ids or []) if fid}
    if selected and use_text_units:
        attributed = [unit for unit in use_text_units if text_unit_file_id(unit)]
        if attributed:
            use_text_units = [
                unit
                for unit in use_text_units
                if text_unit_matches_file_ids(unit, selected)
            ]

    text_units_section_list = [["id", "content", "file_id"]]
    for i, t in enumerate(use_text_units):
        text_units_section_list.append(
            [str(i), t["content"], text_unit_file_id(t)]
        )
    sources_df = list_of_list_to_df(text_units_section_list)
""",
    ),
    (
        """    def _build_graph_search(self):
        file_id = self.file_ids[0]

        # retrieve the graph_id from the index
        with Session(engine) as session:
            graph_id = (
                session.query(self.Index.target_id)
                .filter(self.Index.source_id == file_id)
                .filter(self.Index.relation_type == "graph")
                .first()
            )
            graph_id = graph_id[0] if graph_id else None
            assert graph_id, f"GraphRAG index not found for file_id: {file_id}"
""",
        """    def _build_graph_search(self):
        graph_id = None

        # Collection-wide graphs share one id; still walk the selection
        # instead of assuming only the first selected file matters.
        with Session(engine) as session:
            for file_id in self.file_ids:
                row = (
                    session.query(self.Index.target_id)
                    .filter(self.Index.source_id == file_id)
                    .filter(self.Index.relation_type == "graph")
                    .first()
                )
                if row:
                    graph_id = row[0]
                    break
            assert graph_id, (
                f"GraphRAG index not found for file_ids: {self.file_ids}"
            )
""",
    ),
    (
        """        print("search_type", self.search_type)
        query_params = QueryParam(mode=self.search_type, only_need_context=True)

        return graphrag_func, query_params
""",
        """        print("search_type", self.search_type)
        query_kwargs = {"mode": self.search_type, "only_need_context": True}
        try:
            query_params = QueryParam(**query_kwargs, ids=list(self.file_ids))
        except TypeError:
            # Current LightRAG dropped QueryParam.ids; source filter is below.
            query_params = QueryParam(**query_kwargs)

        return graphrag_func, query_params
""",
    ),
    (
        """            entities, relationships, sources = asyncio.run(
                lightrag_build_local_query_context(graphrag_func, text, query_params)
            )
""",
        """            entities, relationships, sources = asyncio.run(
                lightrag_build_local_query_context(
                    graphrag_func, text, query_params, file_ids=self.file_ids
                )
            )
""",
    ),
    (
        """        header = "\\n<b>Sources</b>\\n"
        context = ""
        for _, row in sources.iterrows():
            title, content = row["id"], row["content"]
""",
        """        header = "\\n<b>Sources</b>\\n"
        context = ""
        selected = {str(fid) for fid in (self.file_ids or []) if fid}
        if selected and hasattr(sources, "columns") and "file_id" in sources.columns:
            tagged = sources["file_id"].fillna("").astype(str)
            if tagged.str.len().gt(0).any():
                sources = sources[tagged.isin(selected)]
        for _, row in sources.iterrows():
            title, content = row["id"], row["content"]
""",
    ),
)


def load_base() -> str:
    return BASE_FILE.read_text(encoding="utf-8")


def apply_kotaemon_758(base: str) -> str:
    text = base
    if "def text_unit_file_id(" not in text:
        marker = "async def lightrag_build_local_query_context(\n"
        idx = text.find(marker)
        if idx < 0:
            raise ValueError("pinned kotaemon snapshot is missing lightrag_build_local_query_context")
        text = text[:idx] + _HELPERS + text[idx:]
    for old, new in _REPLACEMENTS:
        if old not in text:
            raise ValueError(f"pinned kotaemon snapshot drifted; missing hunk:\n{old[:160]}")
        text = text.replace(old, new, 1)
    return text


def upstream_patch_text(base: str | None = None) -> str:
    original = base if base is not None else load_base()
    patched = apply_kotaemon_758(original)
    return unified_files_diff({UPSTREAM_PATH: original}, {UPSTREAM_PATH: patched})
