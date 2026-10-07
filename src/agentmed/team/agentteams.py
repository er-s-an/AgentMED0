from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from agentmed.config import Settings
from agentmed.live import LiveStackError, _docker

REPO_ROOT = Path(__file__).resolve().parents[3]
PACK_DIR = REPO_ROOT / "agentteams"
WORKER_ORDER = (
    "quality-officer",
    "intake",
    "investigator",
    "attribution",
    "builder",
    "verifier",
    "curator",
)
WORKER_SKILLS = {
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
PUSH_SCRIPT = "/opt/agentteams/agent/skills/worker-management/scripts/push-worker-skills.sh"


def _run(cmd: list[str], *, check: bool = True, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=check, timeout=timeout)


def copy_skills(settings: Settings) -> Path:
    dest_root = Path(settings.agentteams_workspace) / "worker-skills"
    dest_root.mkdir(parents=True, exist_ok=True)
    src_root = PACK_DIR / "skills"
    for skill_dir in sorted(src_root.iterdir()):
        if not skill_dir.is_dir():
            continue
        target = dest_root / skill_dir.name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(skill_dir, target)
    return dest_root


def list_worker_names() -> list[str]:
    docker = _docker()
    result = _run([docker, "exec", "agentteams-controller", "agt", "get", "workers"], check=False)
    if result.returncode != 0:
        return []
    names: list[str] = []
    for line in (result.stdout or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.upper().startswith("NAME"):
            continue
        names.append(stripped.split()[0])
    return names


def leader_contact() -> dict[str, str]:
    docker = _docker()
    result = _run(
        [docker, "exec", "agentteams-controller", "agt", "get", "workers", "quality-officer", "-o", "json"],
        check=False,
    )
    if result.returncode != 0 or not (result.stdout or "").strip():
        return {
            "matrix_id": "@quality-officer:matrix-local.agentteams.io:18080",
            "room_id": "",
        }
    payload = json.loads(result.stdout)
    return {
        "matrix_id": payload.get("matrixUserID") or "@quality-officer:matrix-local.agentteams.io:18080",
        "room_id": payload.get("roomID") or "",
    }


def _copy_skill_into_worker(worker: str, skill: str) -> str:
    docker = _docker()
    container = f"agentteams-worker-{worker}"
    dest_parent = f"/root/.copaw-worker/{worker}/skills"
    src = PACK_DIR / "skills" / skill
    if not (src / "SKILL.md").exists():
        raise LiveStackError(f"skill missing: {src}")
    _run([docker, "exec", container, "mkdir", "-p", dest_parent], check=False)
    _run([docker, "exec", container, "rm", "-rf", f"{dest_parent}/{skill}"], check=False)
    copied = _run([docker, "cp", str(src), f"{container}:{dest_parent}/{skill}"], check=False)
    if copied.returncode != 0:
        raise LiveStackError(f"docker cp {skill} → {worker} failed: {copied.stderr or copied.stdout}")
    _run(
        [
            docker,
            "exec",
            container,
            "bash",
            "-lc",
            f"chmod -R a+rX {dest_parent}/{skill} && chmod +x {dest_parent}/{skill}/scripts/*.sh 2>/dev/null || true",
        ],
        check=False,
    )
    return f"{container}:{dest_parent}/{skill}"


def sync_worker_skills(settings: Settings) -> dict[str, Any]:
    """Persist Kernel skills for Workers without requiring them to be awake."""
    del settings
    docker = _docker()
    installed: list[str] = []
    for worker, skills in WORKER_SKILLS.items():
        pushed = _run(
            [
                docker,
                "exec",
                "agentteams-manager",
                "bash",
                PUSH_SCRIPT,
                "--worker",
                worker,
                "--no-notify",
            ],
            check=False,
            timeout=120,
        )
        if pushed.returncode != 0:
            detail = (pushed.stderr or pushed.stdout).strip()
            raise LiveStackError(f"persistent skill push failed for {worker}: {detail}")
        installed.extend(f"agentteams-storage:{worker}/skills/{skill}" for skill in skills)
    try:
        peer = _run(
            [
                docker,
                "exec",
                "agentteams-controller",
                "agt",
                "update",
                "team",
                "--name",
                "agentmed-quality",
                "--peer-mentions=true",
            ],
            check=False,
            timeout=20,
        )
        peer_text = (peer.stdout or peer.stderr).strip()[:500]
    except subprocess.TimeoutExpired:
        peer_text = "timeout"
    return {"installed": installed, "peer_mentions": peer_text}


def apply_pack(settings: Settings | None = None) -> dict[str, Any]:
    """Load AgentMED workers/team/skills onto a running AgentTeams cluster."""
    settings = settings or Settings()
    docker = _docker()
    inspect = _run(
        [docker, "inspect", "-f", "{{.State.Running}}", "agentteams-controller"],
        check=False,
    )
    if inspect.returncode != 0 or inspect.stdout.strip() != "true":
        raise LiveStackError("agentteams-controller is not running; install with scripts/live-stack.sh")
    skills = copy_skills(settings)
    existing = set(list_worker_names())
    applied: list[str] = []
    if not existing.issuperset(WORKER_ORDER):
        remote = "/tmp/agentmed-pack"
        _run([docker, "exec", "agentteams-controller", "rm", "-rf", remote], check=False)
        _run([docker, "cp", str(PACK_DIR), f"agentteams-controller:{remote}"])
        for name in WORKER_ORDER:
            if name in existing:
                continue
            rel = f"workers/{name}.yaml"
            result = _run(
                [docker, "exec", "agentteams-controller", "agt", "apply", "-f", f"{remote}/{rel}"],
                check=False,
            )
            if result.returncode != 0:
                raise LiveStackError(f"agt apply {rel} failed: {result.stderr or result.stdout}")
            applied.append(rel)
        team_result = _run(
            [docker, "exec", "agentteams-controller", "agt", "apply", "-f", f"{remote}/team.yaml"],
            check=False,
        )
        if team_result.returncode != 0:
            raise LiveStackError(f"agt apply team.yaml failed: {team_result.stderr or team_result.stdout}")
        applied.append("team.yaml")
    synced = sync_worker_skills(settings)
    from agentmed.team.dispatch import retarget_agentteams_llm

    llm_proxy = retarget_agentteams_llm(settings)
    workers = _run([docker, "exec", "agentteams-controller", "agt", "get", "workers"], check=False)
    return {
        "skills_dir": str(skills),
        "applied": applied,
        "synced": synced,
        "llm_proxy": llm_proxy,
        "workers": (workers.stdout or workers.stderr).strip(),
    }


def ensure_pack(settings: Settings) -> dict[str, Any]:
    if not list_worker_names():
        return apply_pack(settings)
    copy_skills(settings)
    return {"status": "workers-present", "synced": sync_worker_skills(settings)}
