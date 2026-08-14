from __future__ import annotations

from pathlib import Path
from typing import Any

from agentmed.kernel import Kernel
from agentmed.workloads import adapter_for_case


def case_manifest(kernel: Kernel, case_id: str, *, data_dir: Path | None = None) -> dict[str, Any]:
    bundle = kernel.export_case(case_id)
    case = bundle["case"]
    adapter = adapter_for_case(kernel, case)
    reports = bundle.get("gate_reports") or []
    verified = bundle.get("verified_candidates") or []
    patch = None
    patch_text = None
    for op in bundle.get("operations") or []:
        if op.get("kind") != "draft_pr":
            continue
        receipt = op.get("receipt") or op.get("observed")
        if receipt:
            patch = str(receipt)
    if patch and Path(patch).is_file():
        patch_text = Path(patch).read_text(encoding="utf-8")
    elif data_dir:
        fallback = Path(data_dir) / "runtime" / case_id / "draft.patch"
        if fallback.is_file():
            patch = str(fallback)
            patch_text = fallback.read_text(encoding="utf-8")
    signal = bundle.get("signal") or {}
    last_report = next(
        (item for item in reversed(reports) if item.get("purpose") != "RELEASE_AUTHORIZATION"),
        reports[-1] if reports else {},
    )
    last_verified = verified[-1] if verified else {}
    pack_dir = None
    if data_dir:
        candidate = Path(data_dir) / "pr-packs" / case["id"] / "manifest.json"
        if candidate.is_file():
            pack_dir = str(candidate.parent)
    return {
        "case_id": case["id"],
        "state": case.get("state"),
        "title": case.get("title") or signal.get("title"),
        "workload": adapter.spec.slug,
        "source_ref": signal.get("source_ref"),
        "gate_verdict": last_report.get("verdict"),
        "verified_status": last_verified.get("status"),
        "draft_patch": patch,
        "prior_regression_assets": kernel.prior_regression_assets(case_id),
        "next": kernel.next_actions(case_id),
        "unauthorized_external": 0,
        "digest": bundle.get("digest"),
        "patch_text": patch_text,
        "upstream_issue": adapter.spec.upstream_issue,
        "pr_pack": pack_dir,
        "assurance": ((bundle.get("version_snapshot") or {}).get("manifest") or {}).get("components") or [],
        "episode_missing": (bundle.get("episode_snapshot") or {}).get("missing") or [],
        "acceptance_draft_id": case.get("acceptance_draft_id"),
        "work_order_id": case.get("work_order_id"),
        "approval_id": case.get("approval_id"),
        "release_plan_id": case.get("release_plan_id"),
        "gate_surfaces": (last_report.get("evidence") or {}).get("surfaces") or [],
        "surface_results": [
            {
                "surface": row.get("surface"),
                "verified": bool(
                    row.get("base_reproduces_failure")
                    and row.get("candidate_fail_to_pass")
                    and row.get("known_bad_intercepted")
                ),
            }
            for row in (last_report.get("evidence") or {}).get("by_surface") or []
        ],
        "harness_verified": "harness" in ((last_report.get("evidence") or {}).get("surfaces") or [])
        and last_report.get("verdict") == "VERIFIED",
        "upstream_verified": "upstream" in ((last_report.get("evidence") or {}).get("surfaces") or [])
        and last_report.get("verdict") == "VERIFIED",
    }


def case_review(kernel: Kernel, case_id: str, *, data_dir: Path | None = None) -> dict[str, Any]:
    bundle = kernel.export_case(case_id)
    case = bundle["case"]
    adapter = adapter_for_case(kernel, case)
    manifest = case_manifest(kernel, case_id, data_dir=data_dir)
    spec = adapter.spec
    return {
        "manifest": manifest,
        "case": case,
        "signal": bundle.get("signal"),
        "acceptance_spec": bundle.get("acceptance_spec"),
        "acceptance_draft": bundle.get("acceptance_draft"),
        "version_snapshot": bundle.get("version_snapshot"),
        "episode_snapshot": bundle.get("episode_snapshot"),
        "gate_reports": bundle.get("gate_reports") or [],
        "verified_candidates": bundle.get("verified_candidates") or [],
        "release_plans": bundle.get("release_plans") or [],
        "work_orders": bundle.get("work_orders") or [],
        "approvals": bundle.get("approvals") or [],
        "operations": bundle.get("operations") or [],
        "regression_assets": bundle.get("regression_assets") or [],
        "applications": kernel.store.list("applications"),
        "workload": spec.as_dict(),
        "next": manifest["next"],
        "defaults": {
            "expected_behavior": spec.default_expected,
            "badcase_input": spec.default_badcase,
            "judge": spec.default_judge,
            "probes": list(spec.default_probes),
            "lessons": spec.default_lessons,
            "attribute_hypothesis": spec.attribute_hypothesis,
        },
    }
