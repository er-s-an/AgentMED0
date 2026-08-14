from __future__ import annotations

import difflib
import hashlib
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class WorkloadSpec:
    slug: str
    name: str
    repo: str
    commit: str
    path: str
    allowed_files: tuple[str, ...]
    default_expected: str
    default_badcase: str
    default_judge: str
    attribute_hypothesis: str
    builder_instruction: str
    default_probes: tuple[str, ...] = ()
    default_lessons: str = ""
    upstream_issue: str = ""
    upstream_path: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class WorkloadAdapter(Protocol):
    spec: WorkloadSpec

    def base_files(self) -> dict[str, str]: ...

    def golden_files(self) -> dict[str, str]: ...

    def known_bad_files(self) -> dict[str, str]: ...

    def run_eval(self, files: dict[str, str], surface: str = "harness") -> dict[str, Any]: ...

    def snapshot_manifest(self, issue: str | None = None) -> dict[str, Any]: ...

    def eval_surfaces(self) -> list[str]: ...

    def required_surfaces(self) -> list[str]: ...

    def holdout_files(self) -> dict[str, str]: ...

    def upstream_files(self) -> dict[str, str]: ...


def file_digest(content: str | bytes) -> str:
    raw = content.encode("utf-8") if isinstance(content, str) else content
    return hashlib.sha256(raw).hexdigest()


def eval_surfaces_of(adapter: Any) -> list[str]:
    fn = getattr(adapter, "eval_surfaces", None)
    if callable(fn):
        return [str(item) for item in fn()]
    return ["harness"]


def required_surfaces_of(adapter: Any) -> list[str]:
    fn = getattr(adapter, "required_surfaces", None)
    if callable(fn):
        return [str(item) for item in fn()]
    return ["harness"]


def holdout_files_of(adapter: Any) -> dict[str, str]:
    fn = getattr(adapter, "holdout_files", None)
    if callable(fn):
        return dict(fn() or {})
    return {}


def call_run_eval(adapter: Any, files: dict[str, str], surface: str = "harness") -> dict[str, Any]:
    try:
        return adapter.run_eval(files, surface=surface)
    except TypeError:
        if surface != "harness":
            return {
                "passed": False,
                "returncode": 2,
                "stdout": "",
                "stderr": f"adapter does not implement surface={surface}",
                "surface": surface,
            }
        return adapter.run_eval(files)


def run_pytest_eval(eval_dir: Path, files: dict[str, str]) -> dict[str, Any]:
    """Copy candidate files + frozen eval/ into an isolated tree and run pytest."""
    with tempfile.TemporaryDirectory(prefix="agentmed-gate-") as tmp:
        root = Path(tmp)
        for name, content in files.items():
            dest = root / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
        shutil.copytree(eval_dir, root / "eval")
        (root / "conftest.py").write_text("", encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", str(root / "eval"), "-q"],
            cwd=root,
            capture_output=True,
            text=True,
        )
        return {
            "passed": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-4000:],
            "stderr": proc.stderr[-4000:],
        }


def run_probe_eval(probe: Path, files: dict[str, str]) -> dict[str, Any]:
    """Run one named pytest file against candidate files."""
    if not probe.is_file():
        return {
            "passed": False,
            "returncode": 2,
            "stdout": "",
            "stderr": f"missing probe {probe}",
            "probe": str(probe),
        }
    with tempfile.TemporaryDirectory(prefix="agentmed-probe-") as tmp:
        root = Path(tmp)
        for name, content in files.items():
            dest = root / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
        eval_root = root / "eval"
        eval_root.mkdir()
        shutil.copy2(probe, eval_root / probe.name)
        (root / "conftest.py").write_text("", encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", str(eval_root), "-q"],
            cwd=root,
            capture_output=True,
            text=True,
        )
        return {
            "passed": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-2000:],
            "stderr": proc.stderr[-2000:],
            "probe": str(probe),
        }


def unified_files_diff(before: dict[str, str], after: dict[str, str]) -> str:
    chunks: list[str] = []
    for name in sorted(set(before) | set(after)):
        old = before.get(name, "").splitlines(keepends=True)
        new = after.get(name, "").splitlines(keepends=True)
        if old == new:
            continue
        chunks.extend(difflib.unified_diff(old, new, fromfile=f"a/{name}", tofile=f"b/{name}"))
    return "".join(chunks)


def looks_like_unified_diff(text: str) -> bool:
    stripped = (text or "").lstrip()
    return stripped.startswith("--- ") or stripped.startswith("diff --git")


def filter_allowed(files: dict[str, str], allowed: tuple[str, ...]) -> dict[str, str]:
    extra = sorted(set(files) - set(allowed))
    if extra:
        raise ValueError(f"files not allowed for this workload: {extra}")
    return {name: files[name] for name in allowed if name in files}
