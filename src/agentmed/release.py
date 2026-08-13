from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentmed.gate import base_source, known_bad_source, run_eval
from agentmed.kernel import ROLE_PRINCIPALS, Kernel


def apply_candidate_files(files: dict[str, str]) -> str:
    if "lightrag_store.py" in files:
        return files["lightrag_store.py"]
    return base_source()


def verify_candidate(kernel: Kernel, case_id: str, candidate: dict[str, Any]) -> dict[str, Any]:
    base = run_eval(base_source())
    candidate_eval = run_eval(apply_candidate_files(candidate.get("files") or {}))
    known_bad = run_eval(known_bad_source())
    evidence = {
        "base_reproduces_failure": not base["passed"],
        "candidate_fail_to_pass": candidate_eval["passed"],
        "known_bad_intercepted": not known_bad["passed"],
        "base": {"stdout": base["stdout"], "returncode": base["returncode"]},
        "candidate": {"stdout": candidate_eval["stdout"], "returncode": candidate_eval["returncode"]},
        "known_bad": {"stdout": known_bad["stdout"], "returncode": known_bad["returncode"]},
    }
    if evidence["base_reproduces_failure"] and evidence["candidate_fail_to_pass"] and evidence["known_bad_intercepted"]:
        verdict = "VERIFIED"
        risk = "low: frozen eval plus known-bad candidate both behaved as required"
    elif not evidence["base_reproduces_failure"]:
        verdict = "ERROR"
        risk = "base no longer fails; eval or workload drifted"
    elif not evidence["candidate_fail_to_pass"]:
        verdict = "REJECTED"
        risk = "candidate did not make the scoped-file bad case pass"
    else:
        verdict = "REJECTED"
        risk = "known-bad candidate was not intercepted; gate would rubber-stamp"
    report = kernel.submit_gate(
        principal=ROLE_PRINCIPALS["verifier"],
        case_id=case_id,
        verdict=verdict,
        evidence=evidence,
        false_pass_risk=risk,
    )
    return report


def write_shadow_and_rollback(kernel: Kernel, case_id: str, candidate: dict[str, Any], runtime_dir: Path) -> dict[str, Any]:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    target = runtime_dir / "lightrag_store.py"
    previous = base_source()
    target.write_text(previous, encoding="utf-8")
    desired = apply_candidate_files(candidate.get("files") or {})
    target.write_text(desired, encoding="utf-8")
    observed = target.read_text(encoding="utf-8")
    apply_op = kernel.record_operation(
        principal=ROLE_PRINCIPALS["controller"],
        case_id=case_id,
        kind="shadow_apply",
        desired=desired,
        observed=observed,
        receipt=str(target),
        status="applied" if observed == desired else "drift",
    )
    target.write_text(previous, encoding="utf-8")
    rolled = target.read_text(encoding="utf-8")
    rollback_op = kernel.record_operation(
        principal=ROLE_PRINCIPALS["controller"],
        case_id=case_id,
        kind="rollback",
        desired=previous,
        observed=rolled,
        receipt=str(target),
        status="rolled_back" if rolled == previous else "drift",
    )
    draft = write_draft_patch(kernel, case_id, candidate, runtime_dir)
    return {"apply": apply_op, "rollback": rollback_op, "patch": draft["patch"], "draft": draft}


def write_draft_patch(kernel: Kernel, case_id: str, candidate: dict[str, Any], runtime_dir: Path) -> dict[str, Any]:
    """Local draft.patch only. Never git push or merge."""
    runtime_dir.mkdir(parents=True, exist_ok=True)
    patch_path = runtime_dir / "draft.patch"
    desired = candidate.get("diff") or apply_candidate_files(candidate.get("files") or {})
    patch_path.write_text(desired, encoding="utf-8")
    op = kernel.record_operation(
        principal=ROLE_PRINCIPALS["controller"],
        case_id=case_id,
        kind="draft_pr",
        desired="local draft patch, not merged",
        observed=str(patch_path),
        receipt=str(patch_path),
        status="drafted_not_merged",
    )
    return {"patch": str(patch_path), "operation": op}
