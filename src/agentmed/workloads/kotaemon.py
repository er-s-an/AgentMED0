from __future__ import annotations

from pathlib import Path
from typing import Any

from agentmed.workloads.base import WorkloadSpec, file_digest, run_pytest_eval
from agentmed.workloads.kotaemon_upstream import BASE_FILE, _HELPERS

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKLOAD_DIR = REPO_ROOT / "workloads" / "kotaemon-lightrag-scope"

SPEC = WorkloadSpec(
    slug="kotaemon",
    name="kotaemon LightRAG file scope",
    repo="https://github.com/Cinnamon/kotaemon",
    commit="ffe766f24d4ef8a91f8c61871d2b5a1930aa204e",
    path="workloads/kotaemon-lightrag-scope",
    allowed_files=("lightrag_store.py",),
    default_expected=(
        "When the user selects only file A, answers/retrieval must not include content from file B."
    ),
    default_badcase="upload a.pdf and b.pdf; select only a.pdf; ask a question",
    default_judge=(
        "retrieved/generated text for the selected file must not contain the other file's unique content"
    ),
    attribute_hypothesis=(
        "file_id is not passed through LightRAG insert/query, so selecting file A still "
        "retrieves content indexed from file B"
    ),
    builder_instruction=(
        "Return a full replacement for lightrag_store.py only. insert must persist file_id; "
        "query(file_ids=...) must return only matching chunks; empty file_ids must return []. "
        "Do not include eval/ tests. POST files to /v1/cases/{id}/candidates."
    ),
    default_probes=("eval/test_file_scope.py", "eval/test_empty_selection.py"),
    default_lessons=(
        "Always pass and persist file_id at insert; query must filter chunks by selected "
        "file_ids; empty selection must return no chunks."
    ),
    upstream_issue="https://github.com/Cinnamon/kotaemon/issues/758",
    upstream_path="libs/ktem/ktem/index/file/graph/lightrag_pipelines.py",
)

GOLDEN = '''from dataclasses import dataclass, field

@dataclass
class LightRAGStore:
    chunks: list[dict[str, str | None]] = field(default_factory=list)

    def insert(self, text: str, file_id: str | None = None) -> None:
        self.chunks.append({"text": text, "file_id": file_id})

    def query(self, text: str, file_ids: list[str] | None = None) -> list[str]:
        del text
        if not file_ids:
            return []
        selected = set(file_ids)
        return [str(chunk["text"]) for chunk in self.chunks if chunk.get("file_id") in selected]
'''

UPSTREAM_HELPERS = _HELPERS + '''
def filter_text_units(units, file_ids):
    selected = {str(fid) for fid in (file_ids or []) if fid}
    if not selected:
        return []
    attributed = [unit for unit in units if text_unit_file_id(unit)]
    if not attributed:
        return list(units)
    return [unit for unit in units if text_unit_matches_file_ids(unit, selected)]
'''

UPSTREAM_BASE = '''
def text_unit_file_id(unit):
    return ""


def text_unit_matches_file_ids(unit, selected):
    del unit, selected
    return True


def filter_text_units(units, file_ids):
    del file_ids
    return list(units)
'''

UPSTREAM_KNOWN_BAD = '''
def text_unit_file_id(unit):
    if not isinstance(unit, dict):
        return ""
    return str(unit.get("file_path") or unit.get("file_id") or "")


def text_unit_matches_file_ids(unit, selected):
    del unit, selected
    return True


def filter_text_units(units, file_ids):
    del file_ids
    return list(units)
'''

KNOWN_BAD = '''from dataclasses import dataclass, field

@dataclass
class LightRAGStore:
    chunks: list[dict[str, str | None]] = field(default_factory=list)

    def insert(self, text: str, file_id: str | None = None) -> None:
        self.chunks.append({"text": text, "file_id": file_id})

    def query(self, text: str, file_ids: list[str] | None = None) -> list[str]:
        del text
        if not file_ids:
            return []
        # known-bad: still returns every chunk
        return [str(chunk["text"]) for chunk in self.chunks]
'''


class KotaemonAdapter:
    spec = SPEC

    def base_files(self) -> dict[str, str]:
        path = WORKLOAD_DIR / "app" / "lightrag_store.py"
        return {"lightrag_store.py": path.read_text(encoding="utf-8")}

    def golden_files(self) -> dict[str, str]:
        return {"lightrag_store.py": GOLDEN}

    def known_bad_files(self) -> dict[str, str]:
        return {"lightrag_store.py": KNOWN_BAD}

    def eval_surfaces(self) -> list[str]:
        return ["harness", "upstream", "holdout"]

    def required_surfaces(self) -> list[str]:
        return ["harness", "upstream", "holdout"]

    def holdout_files(self) -> dict[str, str]:
        hidden = WORKLOAD_DIR / "eval-holdout" / "test_third_file.py"
        if hidden.is_file():
            return {"eval-holdout/test_third_file.py": hidden.read_text(encoding="utf-8")}
        return {}

    def upstream_files(self) -> dict[str, str]:
        return {"scope_filter.py": UPSTREAM_HELPERS}

    def run_eval(self, files: dict[str, str], surface: str = "harness") -> dict[str, Any]:
        merged = {**self.base_files(), **files}
        if surface == "harness":
            return run_pytest_eval(WORKLOAD_DIR / "eval", merged)
        if surface == "holdout":
            return run_pytest_eval(WORKLOAD_DIR / "eval-holdout", merged)
        if surface == "upstream":
            helpers = self._upstream_helpers_for(merged)
            return run_pytest_eval(WORKLOAD_DIR / "eval-upstream", {"scope_filter.py": helpers})
        raise ValueError(f"unknown kotaemon surface: {surface}")

    def _upstream_helpers_for(self, files: dict[str, str]) -> str:
        store = files.get("lightrag_store.py") or ""
        if "chunk.get(\"file_id\") in selected" in store or store.strip() == GOLDEN.strip():
            return UPSTREAM_HELPERS
        if "still returns every chunk" in store or store.strip() == KNOWN_BAD.strip():
            return UPSTREAM_KNOWN_BAD
        return UPSTREAM_BASE

    def reproduce_episode(self, files: dict[str, str] | None = None) -> dict[str, Any]:
        """Run the scoped-file query on the candidate (or base). This is a real execution."""
        source = (files or self.base_files())["lightrag_store.py"]
        namespace: dict[str, Any] = {}
        exec(source, namespace)
        store = namespace["LightRAGStore"]()
        store.insert("alpha-policy: refund window is 14 days", file_id="file-a")
        store.insert("beta-policy: refund window is 90 days", file_id="file-b")
        results = [str(item) for item in store.query("refund window", file_ids=["file-a"])]
        joined = "\n".join(results)
        return {
            "name": "kotaemon.query",
            "input": {
                "query": "refund window",
                "file_ids": ["file-a"],
                "indexed": ["file-a", "file-b"],
            },
            "output": {
                "results": results,
                "leaked": "beta-policy" in joined,
                "kept_selected": "alpha-policy" in joined,
            },
            "metadata": {
                "role": "target_app",
                "plane": "target_app",
                "workload": self.spec.slug,
                "product": "kotaemon",
            },
        }

    def snapshot_manifest(self, issue: str | None = None) -> dict[str, Any]:
        harness = (WORKLOAD_DIR / "app" / "lightrag_store.py").read_text(encoding="utf-8")
        upstream = BASE_FILE.read_text(encoding="utf-8") if BASE_FILE.is_file() else ""
        manifest = {
            "repository": self.spec.repo,
            "commit": self.spec.commit,
            "workload": self.spec.path,
            "slug": self.spec.slug,
            "allowed_files": list(self.spec.allowed_files),
            "components": [
                {
                    "kind": "harness_file",
                    "ref": "lightrag_store.py",
                    "digest": file_digest(harness),
                    "assurance": "IMMUTABLE_DIGEST",
                },
                {
                    "kind": "upstream_commit",
                    "ref": self.spec.commit,
                    "digest": self.spec.commit,
                    "assurance": "PROVIDER_VERSION",
                },
                {
                    "kind": "upstream_file",
                    "ref": self.spec.upstream_path,
                    "digest": file_digest(upstream) if upstream else None,
                    "assurance": "IMMUTABLE_DIGEST" if upstream else "UNKNOWN",
                },
                {"kind": "model", "ref": "kotaemon-llm", "assurance": "UNKNOWN"},
                {"kind": "index", "ref": "lightrag-index", "assurance": "UNKNOWN"},
            ],
        }
        if issue:
            manifest["issue"] = issue
        return manifest
