from store_filter import get_filter_condition, search


def test_gte_does_not_let_nine_pass_ten() -> None:
    items = [{"score": n} for n in (2, 9, 10, 11)]
    kept = search(items, {"score": {"$gte": 10}})
    assert [item["score"] for item in kept] == [10, 11]


def test_filter_condition_uses_numeric_cast_for_gte() -> None:
    sql, params = get_filter_condition("score", "$gte", 10)
    assert "numeric" in sql.lower()
    assert "score" in params
    assert 10 in params
