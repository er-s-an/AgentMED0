from __future__ import annotations

KOTAEMON_REPO = "https://github.com/Cinnamon/kotaemon"
KOTAEMON_COMMIT = "ffe766f24d4ef8a91f8c61871d2b5a1930aa204e"
WORKLOAD = "workloads/kotaemon-lightrag-scope"
DEFAULT_EXPECTED = (
    "When the user selects only file A, answers/retrieval must not include content from file B."
)
DEFAULT_BADCASE = "upload a.pdf and b.pdf; select only a.pdf; ask a question"
DEFAULT_JUDGE = (
    "retrieved/generated text for the selected file must not contain the other file's unique content"
)
KOTAEMON_SNAPSHOT = {
    "repository": KOTAEMON_REPO,
    "commit": KOTAEMON_COMMIT,
    "workload": WORKLOAD,
}
ATTRIBUTE_HYPOTHESIS = (
    "file_id is not passed through LightRAG insert/query, so selecting file A still "
    "retrieves content indexed from file B"
)
