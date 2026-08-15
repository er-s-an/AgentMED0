"""Read-only repo scan → system-manifest.draft.json. Import needs a human principal."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentmed.kernel import Kernel
from agentmed.workloads.base import file_digest

PROMPT_GLOBS = (
    "**/prompts/**/*.md",
    "**/prompts/**/*.txt",
    "**/*prompt*.md",
    "**/SKILL.md",
)
TEST_MARKERS = {
    "pyproject.toml": "pytest",
    "package.json": "npm test",
    "Makefile": "make test",
}


def _component(kind: str, ref: str, *, digest: str | None = None, assurance: str = "UNKNOWN") -> dict[str, Any]:
    row = {"kind": kind, "ref": ref, "assurance": assurance}
    if digest:
        row["digest"] = digest
    return row


def draft_system_manifest(repo: Path) -> dict[str, Any]:
    root = repo.resolve()
    components: list[dict[str, Any]] = []
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        components.append(
            _component(
                "python_project",
                "pyproject.toml",
                digest=file_digest(pyproject.read_bytes()),
                assurance="IMMUTABLE_DIGEST",
            )
        )
    package = root / "package.json"
    if package.is_file():
        components.append(
            _component(
                "node_project",
                "package.json",
                digest=file_digest(package.read_bytes()),
                assurance="IMMUTABLE_DIGEST",
            )
        )
    seen_prompts = 0
    for pattern in PROMPT_GLOBS:
        for path in sorted(root.glob(pattern)):
            if not path.is_file() or "node_modules" in path.parts or ".venv" in path.parts:
                continue
            rel = str(path.relative_to(root))
            components.append(
                _component("prompt", rel, digest=file_digest(path.read_bytes()), assurance="IMMUTABLE_DIGEST")
            )
            seen_prompts += 1
            if seen_prompts >= 12:
                break
        if seen_prompts >= 12:
            break
    test_ref = "unknown"
    test_assurance = "UNKNOWN"
    for name, command in TEST_MARKERS.items():
        if (root / name).is_file():
            test_ref = command
            test_assurance = "OBSERVED_ONLY"
            break
    components.append(_component("test_command", test_ref, assurance=test_assurance))
    components.append(_component("model", "unspecified", assurance="UNKNOWN"))
    components.append(_component("index", "unspecified", assurance="UNKNOWN"))
    return {
        "schema": "agentmed.system-manifest.draft",
        "repo": str(root),
        "complete": False,
        "note": "Draft only. UNKNOWN means we did not observe a pin. --import writes this, it does not invent a system graph.",
        "components": components,
    }


def write_draft(repo: Path, dest: Path | None = None) -> Path:
    manifest = draft_system_manifest(repo)
    path = dest or (repo / "system-manifest.draft.json")
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def import_draft(kernel: Kernel, *, principal: str, repo: Path, slug: str | None = None) -> dict[str, Any]:
    if not principal.startswith("human:"):
        raise PermissionError("agentmed init --import requires a human: principal")
    manifest = draft_system_manifest(repo)
    key = slug or repo.resolve().name.lower().replace(" ", "-")
    app = kernel.ensure_app(slug=key, name=repo.resolve().name, repo=str(repo.resolve()))
    app["manifest"] = manifest
    app["imported_by"] = principal
    kernel.store.put("applications", app)
    kernel.audit("application.import", principal, app["id"], {"slug": key, "complete": False})
    return {"application": app, "manifest": manifest}
