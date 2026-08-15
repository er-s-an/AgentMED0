from __future__ import annotations

from pathlib import Path
from typing import Any

from agentmed.workloads.base import WorkloadSpec, file_digest, run_pytest_eval

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKLOAD_DIR = REPO_ROOT / "workloads" / "langgraph-numeric-filter"

SPEC = WorkloadSpec(
    slug="langgraph",
    name="LangGraph PostgresStore numeric filter",
    repo="https://github.com/langchain-ai/langgraph",
    commit="6f83cc9dc2a24c7884ae7da20c9f39f469be35d7",
    path="workloads/langgraph-numeric-filter",
    allowed_files=("store_filter.py",),
    default_expected="filter score $gte 10 must not include score=9",
    default_badcase="items with score 2,9,10,11 and filter {score: {$gte: 10}}",
    default_judge="eval/test_numeric_gte.py",
    attribute_hypothesis=(
        "PostgresStore._get_filter_condition uses value->>key (TEXT) and str(value), "
        "so '9' >= '10' is true and score=9 leaks through $gte 10"
    ),
    builder_instruction=(
        "Return a full replacement for store_filter.py only. Numeric $gt/$gte/$lt/$lte "
        "must compare numbers, not strings. get_filter_condition must emit a NUMERIC cast. "
        "Do not include eval/ tests. POST files to /v1/cases/{id}/candidates."
    ),
    default_probes=("eval/test_numeric_gte.py",),
    default_lessons=(
        "Never compare JSON-extracted numbers as text. Cast to numeric (or compare in-process "
        "as int/float) for $gt/$gte/$lt/$lte."
    ),
    upstream_issue="https://github.com/langchain-ai/langgraph/issues/7684",
    upstream_path="libs/checkpoint-postgres/langgraph/store/postgres/base.py",
)

GOLDEN = '''from __future__ import annotations

from typing import Any


def get_filter_condition(key: str, op: str, value: Any) -> tuple[str, list[Any]]:
    if op == "$eq":
        return "value->%s = %s::jsonb", [key, value]
    if op in {"$gt", "$gte", "$lt", "$lte"} and isinstance(value, (int, float)):
        sql_op = {"$gt": ">", "$gte": ">=", "$lt": "<", "$lte": "<="}[op]
        return f"(jsonb_typeof(value->%s) = \\'number\\' AND CAST(value->>%s AS NUMERIC) {sql_op} %s)", [
            key,
            key,
            value,
        ]
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
    if op in {"$gt", "$gte", "$lt", "$lte"} and isinstance(left, (int, float)) and isinstance(right, (int, float)):
        if op == "$gt":
            return left > right
        if op == "$gte":
            return left >= right
        if op == "$lt":
            return left < right
        return left <= right
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
'''

KNOWN_BAD = '''from __future__ import annotations

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
'''


class LangGraphAdapter:
    spec = SPEC

    def base_files(self) -> dict[str, str]:
        path = WORKLOAD_DIR / "app" / "store_filter.py"
        return {"store_filter.py": path.read_text(encoding="utf-8")}

    def golden_files(self) -> dict[str, str]:
        return {"store_filter.py": GOLDEN}

    def known_bad_files(self) -> dict[str, str]:
        return {"store_filter.py": KNOWN_BAD}

    def eval_surfaces(self) -> list[str]:
        return ["harness"]

    def required_surfaces(self) -> list[str]:
        return ["harness"]

    def holdout_files(self) -> dict[str, str]:
        return {}

    def upstream_files(self) -> dict[str, str]:
        return {}

    def run_eval(self, files: dict[str, str], surface: str = "harness") -> dict[str, Any]:
        if surface != "harness":
            raise ValueError(f"langgraph only implements harness, not {surface}")
        merged = {**self.base_files(), **files}
        return run_pytest_eval(WORKLOAD_DIR / "eval", merged)

    def snapshot_manifest(self, issue: str | None = None) -> dict[str, Any]:
        excerpt = self.base_files()["store_filter.py"]
        manifest = {
            "repository": self.spec.repo,
            "commit": self.spec.commit,
            "workload": self.spec.path,
            "slug": self.spec.slug,
            "allowed_files": list(self.spec.allowed_files),
            "components": [
                {
                    "kind": "harness_file",
                    "ref": "store_filter.py",
                    "digest": file_digest(excerpt),
                    "assurance": "IMMUTABLE_DIGEST",
                },
                {
                    "kind": "upstream_commit",
                    "ref": self.spec.commit,
                    "digest": self.spec.commit,
                    "assurance": "PROVIDER_VERSION",
                },
                {"kind": "postgres", "ref": "not-connected", "assurance": "UNKNOWN"},
                {"kind": "model", "ref": "unspecified", "assurance": "UNKNOWN"},
            ],
        }
        if issue:
            manifest["issue"] = issue
        return manifest
