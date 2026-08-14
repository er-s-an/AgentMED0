from scope_filter import filter_text_units, text_unit_file_id, text_unit_matches_file_ids


def test_helpers_attribute_file_path() -> None:
    unit = {"content": "alpha-policy", "file_path": "file-a"}
    assert text_unit_file_id(unit) == "file-a"
    assert text_unit_matches_file_ids(unit, {"file-a"})
    assert not text_unit_matches_file_ids(unit, {"file-b"})


def test_filter_drops_other_files() -> None:
    units = [
        {"content": "alpha-policy", "file_path": "file-a"},
        {"content": "beta-policy", "file_path": "file-b"},
    ]
    kept = filter_text_units(units, ["file-a"])
    joined = "\n".join(str(item.get("content")) for item in kept)
    assert "alpha-policy" in joined
    assert "beta-policy" not in joined


def test_empty_selection_returns_nothing() -> None:
    units = [{"content": "secret", "file_path": "file-a"}]
    assert filter_text_units(units, []) == []
    assert filter_text_units(units, None) == []
