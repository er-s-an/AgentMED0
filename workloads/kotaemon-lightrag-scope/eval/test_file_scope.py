from lightrag_store import LightRAGStore


def test_selected_file_does_not_leak_other_files():
    store = LightRAGStore()
    store.insert("alpha-policy: refund window is 14 days", file_id="file-a")
    store.insert("beta-policy: refund window is 90 days", file_id="file-b")
    results = store.query("refund window", file_ids=["file-a"])
    joined = "\n".join(results)
    assert "alpha-policy" in joined
    assert "beta-policy" not in joined
