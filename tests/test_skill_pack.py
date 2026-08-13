from __future__ import annotations

from pathlib import Path

from agentmed.team.agentteams import WORKER_SKILLS

REPO = Path(__file__).resolve().parents[1]
SKILLS = REPO / "agentteams" / "skills"

REQUIRED_HEADINGS = (
    "## 输入",
    "## 输出",
    "## 调用条件",
    "## 依赖",
    "## 失败处理",
    "## 安全边界",
    "## 复用价值",
)

EXPECTED_WORKER_SKILLS = {
    "quality-officer": ("coordinate-loop", "release-observe-rollback", "draft-pr"),
    "intake": ("ingest-signal", "ingest-langfuse", "provision-langfuse"),
    "investigator": (
        "bind-version-snapshot",
        "query-langfuse",
        "reproduce-badcase",
        "connect-observability",
        "provision-langfuse",
    ),
    "attribution": ("query-langfuse", "attribute-skip"),
    "builder": ("propose-candidate",),
    "verifier": ("independent-verify", "query-langfuse"),
    "curator": ("curate-regression-asset",),
}


def _first_party_skills() -> list[Path]:
    return sorted(path for path in SKILLS.iterdir() if path.is_dir() and path.name != "langfuse")


def test_first_party_skills_have_contract_and_run_sh() -> None:
    skills = _first_party_skills()
    assert skills, "expected first-party skills under agentteams/skills/"
    for skill in skills:
        markdown = skill / "SKILL.md"
        script = skill / "scripts" / "run.sh"
        assert markdown.is_file(), f"missing {markdown}"
        text = markdown.read_text(encoding="utf-8")
        for heading in REQUIRED_HEADINGS:
            assert heading in text, f"{skill.name} SKILL.md missing {heading}"
        assert "哪个 Agent" in text, f"{skill.name} SKILL.md missing 哪个 Agent"
        assert script.is_file(), f"missing {script}"
        body = script.read_text(encoding="utf-8")
        assert body.startswith("#!"), f"{script} needs a shebang"
        if skill.name == "coordinate-loop":
            poll = skill / "scripts" / "poll.sh"
            assert poll.is_file(), "coordinate-loop must ship scripts/poll.sh"
            combined = body + poll.read_text(encoding="utf-8")
            assert "AGENTMED_KERNEL_URL" in combined or "host.docker.internal:8088" in combined
        else:
            assert "X-AgentMED-Principal" in body, f"{script} must send X-AgentMED-Principal"


def test_official_langfuse_skill_is_unmodified_vendor() -> None:
    vendor = (SKILLS / "langfuse" / "SKILL.md").read_text(encoding="utf-8")
    assert "AgentMED" not in vendor
    assert not (SKILLS / "langfuse" / "scripts" / "run.sh").exists()


def _yaml_skills(worker: str) -> tuple[str, ...]:
    text = (REPO / "agentteams" / "workers" / f"{worker}.yaml").read_text(encoding="utf-8")
    names: list[str] = []
    in_skills = False
    for line in text.splitlines():
        if line.strip() == "skills:":
            in_skills = True
            continue
        if in_skills:
            if line.startswith("    - "):
                names.append(line.strip()[2:].strip())
            elif line.strip() and not line.startswith("    "):
                break
    return tuple(names)


def test_worker_skills_match_pack_and_exclude_vendor_langfuse() -> None:
    assert WORKER_SKILLS == EXPECTED_WORKER_SKILLS
    assigned = {name for skills in WORKER_SKILLS.values() for name in skills}
    assert "langfuse" not in assigned
    for worker, skills in WORKER_SKILLS.items():
        assert _yaml_skills(worker) == skills, worker
