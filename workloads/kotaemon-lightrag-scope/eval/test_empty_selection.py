from lightrag_store import LightRAGStore


def test_query_without_selection_returns_nothing():
    store = LightRAGStore()
    store.insert("secret from A", file_id="file-a")
    assert store.query("secret", file_ids=[]) == []
    assert store.query("secret", file_ids=None) == []
