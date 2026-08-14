from __future__ import annotations

from pathlib import Path
from typing import Any

from agentmed.config import load_settings
from agentmed.kernel import ROLE_PRINCIPALS, Kernel, KernelError
from agentmed.workloads import adapter_for_case
from agentmed.workloads.base import (
    call_run_eval,
    eval_surfaces_of,
    looks_like_unified_diff,
    required_surfaces_of,
    run_probe_eval,
    unified_files_diff,
)


def _write_tree(root: Path, files: dict[str, str]) -> None:
    for name, content in files.items():
        dest = root / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")


def _read_tree(root: Path, names: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for name in names:
        path = root / name
        if path.is_file():
            out[name] = path.read_text(encoding="utf-8")
    return out


def candidate_patch(kernel: Kernel, case_id: str, candidate: dict[str, Any]) -> str:
    adapter = adapter_for_case(kernel, kernel._case(case_id))
    files = dict(candidate.get("files") or {})
    raw = str(candidate.get("diff") or "")
    if looks_like_unified_diff(raw):
        return raw
    return unified_files_diff(adapter.base_files(), {**adapter.base_files(), **files})


def _workload_root(adapter: Any) -> Path:
    from pathlib import Path as P

    repo_root = P(__file__).resolve().parents[2]
    return repo_root / adapter.spec.path


def _run_regression(adapter: Any, files: dict[str, str], assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    root = _workload_root(adapter)
    results: list[dict[str, Any]] = []
    for asset in assets:
        for probe in asset.get("probes") or []:
            path = root / str(probe)
            ran = run_probe_eval(path, files)
            results.append(
                {
                    "asset_id": asset.get("id"),
                    "case_id": asset.get("case_id"),
                    "probe": str(probe),
                    "passed": ran["passed"],
                    "returncode": ran["returncode"],
                    "stdout": ran.get("stdout"),
                    "stderr": ran.get("stderr"),
                }
            )
    return results


def _surface_triplet(adapter: Any, files: dict[str, str], surface: str) -> dict[str, Any]:
    base = call_run_eval(adapter, adapter.base_files(), surface)
    candidate_eval = call_run_eval(adapter, files, surface)
    known_bad = call_run_eval(adapter, adapter.known_bad_files(), surface)
    return {
        "surface": surface,
        "base_reproduces_failure": not base["passed"],
        "candidate_fail_to_pass": candidate_eval["passed"],
        "known_bad_intercepted": not known_bad["passed"],
        "base": {"stdout": base.get("stdout"), "returncode": base.get("returncode")},
        "candidate": {"stdout": candidate_eval.get("stdout"), "returncode": candidate_eval.get("returncode")},
        "known_bad": {"stdout": known_bad.get("stdout"), "returncode": known_bad.get("returncode")},
    }


def verify_candidate(kernel: Kernel, case_id: str, candidate: dict[str, Any]) -> dict[str, Any]:
    case = kernel._case(case_id)
    episode = kernel.store.get("episode_snapshots", case.get("episode_snapshot_id") or "")
    if not episode or not episode.get("sealed"):
        raise KernelError("NEEDS_EPISODE_SNAPSHOT")
    adapter = adapter_for_case(kernel, case)
    files = {**adapter.base_files(), **dict(candidate.get("files") or {})}
    surfaces = eval_surfaces_of(adapter)
    required = set(required_surfaces_of(adapter))
    by_surface = [_surface_triplet(adapter, files, surface) for surface in surfaces]
    prior = kernel.prior_regression_assets(case_id)
    regression = _run_regression(adapter, files, prior)
    regression_failed = any(not item["passed"] for item in regression)
    required_rows = [row for row in by_surface if row["surface"] in required] or by_surface
    harness = next((row for row in by_surface if row["surface"] == "harness"), by_surface[0])
    evidence = {
        "base_reproduces_failure": harness["base_reproduces_failure"],
        "candidate_fail_to_pass": harness["candidate_fail_to_pass"],
        "known_bad_intercepted": harness["known_bad_intercepted"],
        "base": harness["base"],
        "candidate": harness["candidate"],
        "known_bad": harness["known_bad"],
        "workload": adapter.spec.slug,
        "surfaces": surfaces,
        "required_surfaces": sorted(required),
        "by_surface": by_surface,
        "prior_regression_assets": [
            {
                **item,
                "ran": [row for row in regression if row.get("asset_id") == item.get("id")],
            }
            for item in prior
        ],
        "regression_probes": regression,
        "episode_snapshot_id": episode["id"],
        "episode_digest": episode.get("digest"),
        "purpose": "CANDIDATE_VERIFICATION",
    }
    from agentmed.langfuse_bus import log_target_episode, reproduce_episode

    episode_run = reproduce_episode(adapter, adapter.base_files())
    if episode_run:
        logged = log_target_episode(load_settings(), case_id=case_id, episode=episode_run)
        evidence["target_episode"] = {
            "name": episode_run.get("name"),
            "leaked": (episode_run.get("output") or {}).get("leaked"),
            "logged_to_langfuse": logged.get("logged"),
        }

    required_ok = all(
        row["base_reproduces_failure"] and row["candidate_fail_to_pass"] and row["known_bad_intercepted"]
        for row in required_rows
    )
    if regression_failed:
        verdict = "REJECTED"
        risk = "a prior RegressionAsset probe failed on this candidate; required surfaces cannot average that away"
    elif required_ok:
        verdict = "VERIFIED"
        risk = "frozen eval plus known-bad candidate both behaved as required on every required surface"
    elif not all(row["base_reproduces_failure"] for row in required_rows):
        verdict = "ERROR"
        risk = "base no longer fails on a required surface; eval or workload drifted"
    elif not all(row["candidate_fail_to_pass"] for row in required_rows):
        verdict = "REJECTED"
        risk = "candidate did not make a required surface pass"
    else:
        verdict = "REJECTED"
        risk = "known-bad candidate was not intercepted on a required surface; gate would rubber-stamp"
    return kernel.submit_gate(
        principal=ROLE_PRINCIPALS["verifier"],
        case_id=case_id,
        verdict=verdict,
        evidence=evidence,
        false_pass_risk=risk,
        purpose="CANDIDATE_VERIFICATION",
    )


def write_shadow_and_rollback(
    kernel: Kernel, case_id: str, candidate: dict[str, Any], runtime_dir: Path
) -> dict[str, Any]:
    adapter = adapter_for_case(kernel, kernel._case(case_id))
    runtime_dir.mkdir(parents=True, exist_ok=True)
    previous = adapter.base_files()
    desired = {**previous, **dict(candidate.get("files") or {})}
    names = list(desired)
    _write_tree(runtime_dir, previous)
    _write_tree(runtime_dir, desired)
    observed = _read_tree(runtime_dir, names)
    apply_op = kernel.record_operation(
        principal=ROLE_PRINCIPALS["controller"],
        case_id=case_id,
        kind="shadow_apply",
        desired=unified_files_diff({}, desired) or ",".join(names),
        observed=unified_files_diff({}, observed) or ",".join(names),
        receipt=str(runtime_dir),
        status="applied" if observed == desired else "drift",
    )
    _write_tree(runtime_dir, previous)
    rolled = _read_tree(runtime_dir, names)
    rollback_op = kernel.record_operation(
        principal=ROLE_PRINCIPALS["controller"],
        case_id=case_id,
        kind="rollback",
        desired=unified_files_diff({}, previous) or ",".join(names),
        observed=unified_files_diff({}, rolled) or ",".join(names),
        receipt=str(runtime_dir),
        status="rolled_back" if rolled == previous else "drift",
    )
    draft = write_draft_patch(kernel, case_id, candidate, runtime_dir)
    return {"apply": apply_op, "rollback": rollback_op, "patch": draft["patch"], "draft": draft}


def write_draft_patch(kernel: Kernel, case_id: str, candidate: dict[str, Any], runtime_dir: Path) -> dict[str, Any]:
    """Local draft.patch only. Never git push or merge."""
    runtime_dir.mkdir(parents=True, exist_ok=True)
    patch_path = runtime_dir / "draft.patch"
    patch = candidate_patch(kernel, case_id, candidate)
    patch_path.write_text(patch, encoding="utf-8")
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
