from lightrag_store import LightRAGStore


def test_third_file_does_not_leak_when_selecting_first() -> None:
    store = LightRAGStore()
    store.insert("alpha-policy: refund window is 14 days", file_id="file-a")
    store.insert("gamma-policy: refund window is 1 day", file_id="file-c")
    results = store.query("refund window", file_ids=["file-a"])
    joined = "\n".join(results)
    assert "alpha-policy" in joined
    assert "gamma-policy" not in joined
