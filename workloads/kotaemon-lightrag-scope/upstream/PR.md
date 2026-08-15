# fix(lightrag): pass file_id through insert/query so selected-file search stays scoped

Related to #758. Does not claim to close it.

## Problem

When a user uploads `a.pdf` and `b.pdf`, then searches only in `a.pdf`, LightRAG answers still include the other file.

The issue already names the two call sites:

- index: `graphrag_func.insert(combined_doc)` does not pass a file id
- query: `_build_graph_search` looks up a graph from the first selected file, then queries the collection-wide graph with no file filter

## Change

- Keep `file_id` from `Document.metadata` while indexing.
- Call LightRAG `insert(texts, ids=..., file_paths=...)` when the installed LightRAG accepts those kwargs; fall back to the old single-blob insert otherwise.
- Walk the selected `file_ids` when resolving the graph, instead of assuming only the first id matters.
- After local retrieval, drop text units that belong to a different file when LightRAG tagged them (`file_path` / `full_doc_id` / …).
- Try `QueryParam(..., ids=file_ids)` if that field still exists. Current LightRAG removed it; the source-chunk filter is the real scope.

## What this does not claim

LightRAG entity / relation descriptions are aggregated across the collection graph. This PR stops **source text** from unselected files appearing in the QA context. Full graph isolation would need per-file graphs, which is a larger change.

Gate evidence (AgentMED) verified the file-id contract on a frozen harness of this failure mode, not a full kotaemon UI run. Please review the call-site wiring against your LightRAG version before merge.

## Test plan

- [ ] Upload `a.pdf` and `b.pdf` into a LightRAG collection
- [ ] Select only `a.pdf` under search-in-files
- [ ] Ask a question whose answer would leak unique text from `b.pdf`
- [ ] Sources / answer must not include `b.pdf`
- [ ] Empty file selection still returns no LightRAG hits
- [ ] Older LightRAG without `insert(..., ids=)` still indexes (unscoped, same as today)
