"""Excerpt of LangGraph PostgresStore._get_filter_condition before the numeric cast.

https://github.com/langchain-ai/langgraph/issues/7684

The live store builds SQL with value->>key (TEXT) and str(value). This module
replays that comparison in-process so Gate does not need Postgres.
"""

from __future__ import annotations

from typing import Any


def get_filter_condition(key: str, op: str, value: Any) -> tuple[str, list[Any]]:
    if op == "$eq":
        return "value->%s = %s::jsonb", [key, value]
    if op == "$gt":
        return "value->>%s > %s", [key, str(value)]
    if op == "$gte":
        return "value->>%s >= %s", [key, str(value)]
    if op == "$lt":
        return "value->>%s < %s", [key, str(value)]
    if op == "$lte":
        return "value->>%s <= %s", [key, str(value)]
    if op == "$ne":
        return "value->%s != %s::jsonb", [key, value]
    raise ValueError(f"Unsupported operator: {op}")


def _compare(left: Any, op: str, right: Any) -> bool:
    # known-bad / base: lexicographic, matching value->>key vs str(value)
    left_text = str(left)
    right_text = str(right)
    if op == "$gt":
        return left_text > right_text
    if op == "$gte":
        return left_text >= right_text
    if op == "$lt":
        return left_text < right_text
    if op == "$lte":
        return left_text <= right_text
    if op == "$eq":
        return left == right
    if op == "$ne":
        return left != right
    raise ValueError(f"Unsupported operator: {op}")


def matches(item: dict[str, Any], filters: dict[str, Any]) -> bool:
    for key, cond in filters.items():
        if isinstance(cond, dict):
            for op, value in cond.items():
                if not _compare(item.get(key), op, value):
                    return False
        elif item.get(key) != cond:
            return False
    return True


def search(items: list[dict[str, Any]], filters: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in items if matches(item, filters)]
