from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKLOAD_APP = REPO_ROOT / "workloads/kotaemon-lightrag-scope/app/lightrag_store.py"
WORKLOAD_EVAL = REPO_ROOT / "workloads/kotaemon-lightrag-scope/eval"
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


def run_eval(store_source: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="agentmed-gate-") as tmp:
        root = Path(tmp)
        (root / "lightrag_store.py").write_text(store_source, encoding="utf-8")
        shutil.copytree(WORKLOAD_EVAL, root / "eval")
        (root / "conftest.py").write_text("", encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", str(root / "eval"), "-q"],
            cwd=root,
            capture_output=True,
            text=True,
        )
        passed = proc.returncode == 0
        return {
            "passed": passed,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-4000:],
            "stderr": proc.stderr[-4000:],
        }


def base_source() -> str:
    return WORKLOAD_APP.read_text(encoding="utf-8")


def known_bad_source() -> str:
    return KNOWN_BAD


def golden_source() -> str:
    return GOLDEN
