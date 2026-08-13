from __future__ import annotations

from pathlib import Path

import pytest

from agentmed.kernel import ROLE_PRINCIPALS, Kernel, KernelError
from agentmed.store import Store


def make_kernel(tmp_path: Path) -> Kernel:
    db = tmp_path / "agentmed.db"
    store = Store(f"sqlite:///{db}", tmp_path / "data")
    return Kernel(store)


def seed_case(kernel: Kernel, *, confirm: bool = False) -> dict:
    app = kernel.ensure_app("kotaemon", "Kotaemon", "local")
    signal = kernel.ingest_signal(
        principal=ROLE_PRINCIPALS["intake"],
        source_type="issue",
        source_ref="kotaemon#758",
        title="file scope leak",
        body="selecting file A returns file B",
        application_id=app["id"],
        raw={"issue": 758},
    )
    case = kernel.open_case(
        principal=ROLE_PRINCIPALS["lead"],
        signal=signal,
        application=app,
    )
    if confirm:
        kernel.confirm_acceptance(
            principal=ROLE_PRINCIPALS["human"],
            case_id=case["id"],
            expected_behavior="query results stay inside selected file_ids",
            badcase_input="file-a vs file-b refund windows",
            judge="eval/test_file_scope.py",
        )
        case = kernel.store.get("cases", case["id"])
    return {"app": app, "signal": signal, "case": case}


def test_signal_ingest_is_idempotent_on_source_ref_and_body(tmp_path: Path) -> None:
    kernel = make_kernel(tmp_path)
    app = kernel.ensure_app("kotaemon", "Kotaemon", "local")
    kwargs = dict(
        principal=ROLE_PRINCIPALS["intake"],
        source_type="issue",
        source_ref="kotaemon#758",
        title="file scope leak",
        body="same body",
        application_id=app["id"],
        raw={},
    )
    first = kernel.ingest_signal(**kwargs)
    second = kernel.ingest_signal(**kwargs)
    assert first["id"] == second["id"]
    assert len(kernel.store.list("signals")) == 1


def test_open_case_is_idempotent_on_signal_id(tmp_path: Path) -> None:
    kernel = make_kernel(tmp_path)
    seeded = seed_case(kernel)
    again = kernel.open_case(
        principal=ROLE_PRINCIPALS["lead"],
        signal=seeded["signal"],
        application=seeded["app"],
    )
    assert again["id"] == seeded["case"]["id"]
    assert len(kernel.store.list("cases")) == 1


def test_non_human_cannot_confirm_acceptance(tmp_path: Path) -> None:
    kernel = make_kernel(tmp_path)
    case = seed_case(kernel)["case"]
    with pytest.raises(KernelError, match="human"):
        kernel.confirm_acceptance(
            principal=ROLE_PRINCIPALS["builder"],
            case_id=case["id"],
            expected_behavior="scoped query",
            badcase_input="file-a",
            judge="eval",
        )


def test_human_cli_can_confirm_acceptance_and_case_investigating(tmp_path: Path) -> None:
    kernel = make_kernel(tmp_path)
    case = seed_case(kernel)["case"]
    spec = kernel.confirm_acceptance(
        principal=ROLE_PRINCIPALS["human"],
        case_id=case["id"],
        expected_behavior="scoped query",
        badcase_input="file-a",
        judge="eval",
    )
    assert spec["confirmed_by"] == "human:cli"
    updated = kernel.store.get("cases", case["id"])
    assert updated["state"] == "investigating"
    assert updated["acceptance_spec_id"] == spec["id"]


def test_non_builder_cannot_submit_candidate(tmp_path: Path) -> None:
    kernel = make_kernel(tmp_path)
    case = seed_case(kernel, confirm=True)["case"]
    with pytest.raises(KernelError, match="builder"):
        kernel.submit_candidate(
            principal=ROLE_PRINCIPALS["investigator"],
            case_id=case["id"],
            summary="fix",
            diff="",
            files={"lightrag_store.py": "x"},
            risk="low",
        )


def test_builder_cannot_submit_candidate_before_acceptance_spec(tmp_path: Path) -> None:
    kernel = make_kernel(tmp_path)
    case = seed_case(kernel)["case"]
    with pytest.raises(KernelError, match="AcceptanceSpec"):
        kernel.submit_candidate(
            principal=ROLE_PRINCIPALS["builder"],
            case_id=case["id"],
            summary="fix",
            diff="",
            files={"lightrag_store.py": "x"},
            risk="low",
        )


def test_only_verifier_can_submit_gate(tmp_path: Path) -> None:
    kernel = make_kernel(tmp_path)
    case = seed_case(kernel, confirm=True)["case"]
    kernel.submit_candidate(
        principal=ROLE_PRINCIPALS["builder"],
        case_id=case["id"],
        summary="fix",
        diff="",
        files={"lightrag_store.py": "x"},
        risk="low",
    )
    with pytest.raises(KernelError, match="verifier"):
        kernel.submit_gate(
            principal=ROLE_PRINCIPALS["lead"],
            case_id=case["id"],
            verdict="VERIFIED",
            evidence={},
            false_pass_risk="n/a",
        )


def test_verified_creates_not_deployed_verified_candidate(tmp_path: Path) -> None:
    kernel = make_kernel(tmp_path)
    case = seed_case(kernel, confirm=True)["case"]
    kernel.submit_candidate(
        principal=ROLE_PRINCIPALS["builder"],
        case_id=case["id"],
        summary="fix",
        diff="",
        files={"lightrag_store.py": "x"},
        risk="low",
    )
    kernel.submit_gate(
        principal=ROLE_PRINCIPALS["verifier"],
        case_id=case["id"],
        verdict="VERIFIED",
        evidence={"ok": True},
        false_pass_risk="low",
    )
    updated = kernel.store.get("cases", case["id"])
    assert updated["state"] == "verified"
    verified = kernel.store.get("verified_candidates", updated["verified_candidate_id"])
    assert verified is not None
    assert verified["deployed"] is False
    assert verified["status"] == "NOT_DEPLOYED"


def test_builder_cannot_submit_gate(tmp_path: Path) -> None:
    kernel = make_kernel(tmp_path)
    case = seed_case(kernel, confirm=True)["case"]
    kernel.submit_candidate(
        principal=ROLE_PRINCIPALS["builder"],
        case_id=case["id"],
        summary="fix",
        diff="",
        files={"lightrag_store.py": "x"},
        risk="low",
    )
    with pytest.raises(KernelError, match="verifier"):
        kernel.submit_gate(
            principal=ROLE_PRINCIPALS["builder"],
            case_id=case["id"],
            verdict="VERIFIED",
            evidence={},
            false_pass_risk="n/a",
        )


def test_reject_then_second_candidate_returns_to_verifying(tmp_path: Path) -> None:
    kernel = make_kernel(tmp_path)
    case = seed_case(kernel, confirm=True)["case"]
    first = kernel.submit_candidate(
        principal=ROLE_PRINCIPALS["builder"],
        case_id=case["id"],
        summary="bad fix",
        diff="",
        files={"lightrag_store.py": "broken"},
        risk="high",
    )
    kernel.submit_gate(
        principal=ROLE_PRINCIPALS["verifier"],
        case_id=case["id"],
        verdict="REJECTED",
        evidence={"passed": False},
        false_pass_risk="candidate failed eval",
    )
    rejected = kernel.store.get("cases", case["id"])
    assert rejected["state"] == "rejected"
    second = kernel.submit_candidate(
        principal=ROLE_PRINCIPALS["builder"],
        case_id=case["id"],
        summary="second fix",
        diff="",
        files={"lightrag_store.py": "fixed"},
        risk="low",
    )
    assert second["id"] != first["id"]
    updated = kernel.store.get("cases", case["id"])
    assert updated["state"] == "verifying"
    assert updated["candidate_id"] == second["id"]


def test_closed_case_opens_a_new_loop_on_same_signal(tmp_path: Path) -> None:
    kernel = make_kernel(tmp_path)
    seeded = seed_case(kernel)
    kernel._set_state(seeded["case"], "closed", ROLE_PRINCIPALS["curator"])
    again = kernel.open_case(
        principal=ROLE_PRINCIPALS["intake"],
        signal=seeded["signal"],
        application=seeded["app"],
    )
    assert again["id"] != seeded["case"]["id"]
    assert again["state"] == "awaiting_acceptance"
    assert kernel.find_case_by_source_ref("kotaemon#758")["id"] == again["id"]
