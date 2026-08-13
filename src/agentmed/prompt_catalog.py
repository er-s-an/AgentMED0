from __future__ import annotations

from pathlib import Path
from typing import Any

from agentmed.prompts import (
    BUILDER_SYSTEM,
    CURATOR_SYSTEM,
    INTAKE_SYSTEM,
    INVESTIGATOR_SYSTEM,
    LEAD_SYSTEM,
    VERIFIER_SYSTEM,
)
from agentmed.team.dispatch import SOUL_APPENDIX

REPO_ROOT = Path(__file__).resolve().parents[2]
PACK_DIR = REPO_ROOT / "agentteams"
VENDOR_SKILLS = frozenset({"langfuse"})
PLAYBOOK_PROMPTS = (
    ("intake", INTAKE_SYSTEM),
    ("lead", LEAD_SYSTEM),
    ("investigator", INVESTIGATOR_SYSTEM),
    ("builder", BUILDER_SYSTEM),
    ("verifier", VERIFIER_SYSTEM),
    ("curator", CURATOR_SYSTEM),
)


def _folded_block(text: str, key: str) -> str:
    prefix = f"{key}:"
    lines = text.splitlines()
    out: list[str] = []
    capture = False
    key_indent: int | None = None
    indent: int | None = None
    for line in lines:
        if not capture:
            stripped = line.strip()
            if stripped.startswith(prefix) and "|" in stripped:
                capture = True
                key_indent = len(line) - len(line.lstrip(" "))
            continue
        raw_indent = len(line) - len(line.lstrip(" ")) if line.strip() else 0
        if line.strip() and key_indent is not None and raw_indent <= key_indent:
            break
        if indent is None:
            if not line.strip():
                out.append("")
                continue
            indent = len(line) - len(line.lstrip(" "))
        out.append(line[indent:] if indent is not None and len(line) >= indent else line.lstrip())
    return "\n".join(out).strip()


def _record(
    *,
    name: str,
    prompt: str,
    role: str,
    kind: str,
    source: str,
) -> dict[str, Any] | None:
    body = (prompt or "").strip()
    if not body:
        return None
    return {
        "name": name,
        "type": "text",
        "prompt": body,
        "role": role,
        "kind": kind,
        "source": source,
        "tags": ["agentmed", "governance", role, kind],
        "labels": ["production", "governance"],
    }


def harvest_prompts(root: Path | None = None) -> list[dict[str, Any]]:
    """Static AgentMED prompts for Langfuse Prompt Management and Kernel audit."""
    base = root or REPO_ROOT
    pack = base / "agentteams"
    records: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(item: dict[str, Any] | None) -> None:
        if not item or item["name"] in seen:
            return
        seen.add(item["name"])
        records.append(item)

    for role, prompt in PLAYBOOK_PROMPTS:
        add(
            _record(
                name=f"agentmed-playbook-{role}",
                prompt=prompt,
                role=role,
                kind="playbook",
                source="src/agentmed/prompts.py",
            )
        )

    add(
        _record(
            name="agentmed-manager-soul-appendix",
            prompt=SOUL_APPENDIX,
            role="manager",
            kind="soul",
            source="src/agentmed/team/dispatch.py",
        )
    )

    workers = pack / "workers"
    if workers.is_dir():
        for path in sorted(workers.glob("*.yaml")):
            role = path.stem
            text = path.read_text(encoding="utf-8")
            rel = str(path.relative_to(base)) if base in path.parents or path.parent == base else str(path)
            for kind in ("identity", "soul", "agents"):
                add(
                    _record(
                        name=f"agentmed-worker-{role}-{kind}",
                        prompt=_folded_block(text, kind),
                        role=role,
                        kind=kind,
                        source=rel,
                    )
                )

    skills = pack / "skills"
    if skills.is_dir():
        for skill_dir in sorted(skills.iterdir()):
            if not skill_dir.is_dir() or skill_dir.name in VENDOR_SKILLS:
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.is_file():
                continue
            rel = str(skill_md.relative_to(base)) if base in skill_md.parents else str(skill_md)
            add(
                _record(
                    name=f"agentmed-skill-{skill_dir.name}",
                    prompt=skill_md.read_text(encoding="utf-8"),
                    role="skill",
                    kind="skill",
                    source=rel,
                )
            )
    return records


def catalog_summary(records: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    items = records if records is not None else harvest_prompts()
    return {
        "count": len(items),
        "names": [item["name"] for item in items],
        "by_role": _count_by(items, "role"),
        "by_kind": _count_by(items, "kind"),
    }


def _count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        label = str(item.get(key) or "unknown")
        counts[label] = counts.get(label, 0) + 1
    return counts
