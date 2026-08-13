from __future__ import annotations

import os
import stat
from pathlib import Path

from agentmed.team.agentteams import WORKER_SKILLS

REPO = Path(__file__).resolve().parents[1]
SKILLS = REPO / "agentteams" / "skills"
WORKERS = REPO / "agentteams" / "workers"

REQUIRED_SUBSTRINGS = (
    "输入",
    "输出",
    "调用条件",
    "依赖",
    "失败",
    "安全边界",
    "复用价值",
    "哪个 Agent",
)


def _first_party_skills() -> list[Path]:
    return sorted(
        path
        for path in SKILLS.iterdir()
        if path.is_dir() and not path.name.startswith(".") and path.name != "langfuse"
    )


def _yaml_skills(path: Path) -> list[str]:
    names: list[str] = []
    in_skills = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if not in_skills:
            if line.strip() == "skills:":
                in_skills = True
            continue
        stripped = line.strip()
        if stripped.startswith("- "):
            names.append(stripped[2:].strip().strip("\"'"))
            continue
        if not stripped:
            continue
        break
    return names


def test_first_party_skills_have_contract_and_run_sh() -> None:
    skills = _first_party_skills()
    assert skills, "expected first-party skills under agentteams/skills/"
    for skill in skills:
        markdown = skill / "SKILL.md"
        script = skill / "scripts" / "run.sh"
        assert markdown.is_file(), f"missing {markdown}"
        text = markdown.read_text(encoding="utf-8")
        for needle in REQUIRED_SUBSTRINGS:
            assert needle in text, f"{skill.name} SKILL.md missing {needle!r}"
        assert script.is_file(), f"missing {script}"
        if os.name != "nt":
            mode = script.stat().st_mode
            assert mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH), f"{script} is not executable"
        body = script.read_text(encoding="utf-8")
        if skill.name == "coordinate-loop":
            assert "poll.sh" in body, f"{script} should exec poll.sh"
            poll = skill / "scripts" / "poll.sh"
            assert poll.is_file(), "coordinate-loop must ship scripts/poll.sh"
            poll_text = poll.read_text(encoding="utf-8")
            assert "X-AgentMED-Principal" in poll_text, "poll.sh must send X-AgentMED-Principal"
        else:
            assert (
                "X-AgentMED-Principal" in body or "AGENTMED_PRINCIPAL" in body
            ), f"{script} must mention X-AgentMED-Principal or AGENTMED_PRINCIPAL"


def test_official_langfuse_skill_is_unmodified_vendor() -> None:
    vendor = (SKILLS / "langfuse" / "SKILL.md").read_text(encoding="utf-8")
    assert "AgentMED pack" not in vendor
    assert "POST /v1/langfuse/provision" not in vendor
    assert not (SKILLS / "langfuse" / "scripts" / "run.sh").exists()


def test_worker_yaml_skills_match_worker_skills() -> None:
    yaml_files = sorted(WORKERS.glob("*.yaml"))
    assert yaml_files, "expected worker YAML under agentteams/workers/"
    yaml_map = {path.stem: _yaml_skills(path) for path in yaml_files}
    assert sorted(yaml_map) == sorted(WORKER_SKILLS)
    for worker, skills in WORKER_SKILLS.items():
        assert yaml_map[worker] == list(skills), f"{worker}: yaml={yaml_map[worker]} WORKER_SKILLS={list(skills)}"
    assigned = {name for skills in WORKER_SKILLS.values() for name in skills}
    assert "langfuse" not in assigned
