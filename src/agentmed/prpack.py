"""Human-reviewable upstream PR pack. Never opened unless a human says so."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from agentmed.kernel import Kernel
from agentmed.release import candidate_patch
from agentmed.review import case_manifest
from agentmed.workloads import adapter_for_case
from agentmed.workloads.kotaemon_upstream import (
    BASE_COMMIT,
    ISSUE_URL,
    REPO,
    UPSTREAM_DIR,
    UPSTREAM_PATH,
    upstream_patch_text,
)

SUBMIT_REFUSAL = (
    "AgentMED will not open an upstream PR. A human must pass --i-am-human."
)


class HumanRequired(RuntimeError):
    pass


class PackNotReady(RuntimeError):
    pass


def pack_dir_for(data_dir: Path, case_id: str) -> Path:
    return Path(data_dir) / "pr-packs" / case_id


def _static_text(name: str) -> str:
    return (UPSTREAM_DIR / name).read_text(encoding="utf-8")


def _harness_patch(kernel: Kernel, case_id: str, manifest: dict[str, Any]) -> str | None:
    text = manifest.get("patch_text")
    if text:
        return str(text)
    path = manifest.get("draft_patch")
    if path and Path(path).is_file():
        return Path(path).read_text(encoding="utf-8")
    case = kernel._case(case_id)
    candidate_id = case.get("candidate_id")
    if not candidate_id:
        return None
    candidate = kernel.store.get("candidates", candidate_id)
    if not candidate:
        return None
    generated = candidate_patch(kernel, case_id, candidate)
    return generated or None


def build_pr_pack(
    kernel: Kernel,
    case_id: str,
    *,
    data_dir: Path,
    write: bool = True,
) -> dict[str, Any]:
    adapter = adapter_for_case(kernel, kernel._case(case_id))
    manifest = case_manifest(kernel, case_id, data_dir=data_dir)
    harness = _harness_patch(kernel, case_id, manifest)
    upstream = ""
    if adapter.spec.slug == "kotaemon":
        upstream = upstream_patch_text()
    last_gate = {}
    case = kernel._case(case_id)
    if case.get("gate_report_id"):
        last_gate = kernel.store.get("gate_reports", case["gate_report_id"]) or {}
    surfaces = list((last_gate.get("evidence") or {}).get("surfaces") or ["harness"])
    ready = (
        manifest.get("gate_verdict") == "VERIFIED"
        and manifest.get("verified_status") == "NOT_DEPLOYED"
        and bool(upstream)
        and "upstream" in surfaces
    )
    pack_dir = pack_dir_for(data_dir, case_id)
    summary = {
        "case_id": case_id,
        "workload": adapter.spec.slug,
        "repo": adapter.spec.repo or REPO,
        "base_commit": adapter.spec.commit or BASE_COMMIT,
        "upstream_issue": adapter.spec.upstream_issue or ISSUE_URL,
        "upstream_path": adapter.spec.upstream_path or UPSTREAM_PATH,
        "gate_verified": "upstream" if "upstream" in surfaces else "harness",
        "gate_surfaces": surfaces,
        "gate_path": "workloads/kotaemon-lightrag-scope/app/lightrag_store.py",
        "not_deployed": True,
        "auto_submit": False,
        "ready_to_submit": ready,
        "submit_command": f"agentmed pr submit {case_id} --i-am-human",
        "dry_run_command": f"agentmed pr submit {case_id} --i-am-human --dry-run",
        "pack_dir": str(pack_dir),
        "unauthorized_external": manifest.get("unauthorized_external", 0),
        "gate_verdict": manifest.get("gate_verdict"),
        "verified_status": manifest.get("verified_status"),
        "title": "fix(lightrag): pass file_id through insert/query so selected-file search stays scoped",
    }
    files = {
        "manifest.json": json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        "PR.md": _static_text("PR.md") if (UPSTREAM_DIR / "PR.md").is_file() else "",
        "SUBMIT.md": _static_text("SUBMIT.md") if (UPSTREAM_DIR / "SUBMIT.md").is_file() else "",
        "README.md": _static_text("README.md") if (UPSTREAM_DIR / "README.md").is_file() else "",
        "upstream.patch": upstream,
    }
    if harness:
        files["harness.patch"] = harness
    if write:
        pack_dir.mkdir(parents=True, exist_ok=True)
        for name, content in files.items():
            (pack_dir / name).write_text(content, encoding="utf-8")
        if (UPSTREAM_DIR / "lightrag_pipelines.base.py").is_file():
            shutil.copy2(
                UPSTREAM_DIR / "lightrag_pipelines.base.py",
                pack_dir / "lightrag_pipelines.base.py",
            )
    return {
        "manifest": summary,
        "files": {name: content for name, content in files.items() if name != "lightrag_pipelines.base.py"},
        "pack_dir": str(pack_dir),
    }


def planned_submit_steps(pack_dir: Path, manifest: dict[str, Any], *, repo_dir: Path | None) -> list[list[str]]:
    title = manifest.get("title") or "fix(lightrag): scope LightRAG QA to selected files"
    patch = pack_dir / "upstream.patch"
    body = pack_dir / "PR.md"
    steps: list[list[str]] = []
    if repo_dir:
        steps.extend(
            [
                ["git", "checkout", "-B", "agentmed/758-lightrag-file-scope", str(manifest.get("base_commit") or BASE_COMMIT)],
                ["git", "apply", str(patch)],
                ["git", "add", str(manifest.get("upstream_path") or UPSTREAM_PATH)],
                ["git", "commit", "-m", title],
                ["git", "push", "-u", "origin", "HEAD"],
            ]
        )
    steps.append(
        [
            "gh",
            "pr",
            "create",
            "--repo",
            "Cinnamon/kotaemon",
            "--title",
            title,
            "--body-file",
            str(body),
        ]
    )
    return steps


def submit_upstream_pr(
    pack_dir: Path,
    *,
    i_am_human: bool,
    dry_run: bool = False,
    repo_dir: Path | None = None,
) -> dict[str, Any]:
    if not i_am_human:
        raise HumanRequired(SUBMIT_REFUSAL)
    pack_dir = Path(pack_dir)
    manifest_path = pack_dir / "manifest.json"
    if not manifest_path.is_file():
        raise PackNotReady(f"missing pack manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not manifest.get("ready_to_submit"):
        raise PackNotReady("pack is not ready_to_submit; Gate must be VERIFIED / NOT_DEPLOYED")
    patch = pack_dir / "upstream.patch"
    if not patch.is_file() or not patch.read_text(encoding="utf-8").strip():
        raise PackNotReady("missing upstream.patch")
    steps = planned_submit_steps(pack_dir, manifest, repo_dir=repo_dir)
    result: dict[str, Any] = {
        "pack_dir": str(pack_dir),
        "command": steps,
        "dry_run": dry_run,
        "repo_dir": str(repo_dir) if repo_dir else None,
        "base_commit": manifest.get("base_commit"),
        "issue": manifest.get("upstream_issue"),
    }
    if dry_run:
        result["status"] = "dry_run"
        return result
    if repo_dir is None:
        raise PackNotReady("actual submit needs --repo-dir pointing at a kotaemon checkout")
    if shutil.which("gh") is None:
        raise PackNotReady("gh is not installed; install GitHub CLI, then rerun with --i-am-human")
    logs: list[dict[str, str]] = []
    for command in steps:
        ran = subprocess.run(command, cwd=repo_dir, capture_output=True, text=True)
        logs.append({"command": " ".join(command), "stdout": ran.stdout, "stderr": ran.stderr})
        if ran.returncode != 0:
            result["status"] = "failed"
            result["logs"] = logs
            raise PackNotReady(ran.stderr or ran.stdout or f"failed: {command[0]}")
    result["status"] = "submitted"
    result["logs"] = logs
    return result


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Human-gated upstream PR submit")
    parser.add_argument("--pack", required=True)
    parser.add_argument("--i-am-human", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--repo-dir")
    args = parser.parse_args(argv)
    try:
        result = submit_upstream_pr(
            Path(args.pack),
            i_am_human=args.i_am_human,
            dry_run=args.dry_run,
            repo_dir=Path(args.repo_dir) if args.repo_dir else None,
        )
    except HumanRequired as exc:
        print(str(exc), file=__import__("sys").stderr)
        return 2
    except PackNotReady as exc:
        print(str(exc), file=__import__("sys").stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
