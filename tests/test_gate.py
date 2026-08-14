from __future__ import annotations

from pathlib import Path

from agentmed.gate import base_source, golden_source, known_bad_source, run_eval
from agentmed.kernel import ROLE_PRINCIPALS, Kernel
from agentmed.release import verify_candidate
from agentmed.store import Store


def make_kernel(tmp_path: Path) -> Kernel:
    db = tmp_path / "agentmed.db"
    store = Store(f"sqlite:///{db}", tmp_path / "data")
    return Kernel(store)


def ready_case(kernel: Kernel) -> dict:
    app = kernel.ensure_app("kotaemon", "Kotaemon", "local")
    signal = kernel.ingest_signal(
        principal=ROLE_PRINCIPALS["intake"],
        source_type="issue",
        source_ref="kotaemon#758",
        title="file scope leak",
        body="selecting file A returns file B",
        application_id=app["id"],
        raw={},
    )
    case = kernel.open_case(
        principal=ROLE_PRINCIPALS["lead"],
        signal=signal,
        application=app,
    )
    kernel.confirm_acceptance(
        principal=ROLE_PRINCIPALS["human"],
        case_id=case["id"],
        expected_behavior="query results stay inside selected file_ids",
        badcase_input="file-a vs file-b refund windows",
        judge="eval/test_file_scope.py",
    )
    kernel.bind_version_snapshot(
        principal=ROLE_PRINCIPALS["investigator"],
        case_id=case["id"],
        manifest={"files": ["lightrag_store.py"]},
    )
    kernel.seal_episode(principal=ROLE_PRINCIPALS["investigator"], case_id=case["id"], coverage={"test": True})
    return kernel.store.get("cases", case["id"])


def test_base_source_eval_fails() -> None:
    result = run_eval(base_source())
    assert result["passed"] is False


def test_golden_source_eval_passes() -> None:
    result = run_eval(golden_source())
    assert result["passed"] is True


def test_known_bad_source_eval_fails() -> None:
    result = run_eval(known_bad_source())
    assert result["passed"] is False


def test_verify_candidate_golden_is_verified(tmp_path: Path) -> None:
    kernel = make_kernel(tmp_path)
    case = ready_case(kernel)
    candidate = kernel.submit_candidate(
        principal=ROLE_PRINCIPALS["builder"],
        case_id=case["id"],
        summary="scope query by file_id",
        diff="",
        files={"lightrag_store.py": golden_source()},
        risk="low",
    )
    report = verify_candidate(kernel, case["id"], candidate)
    assert report["verdict"] == "VERIFIED"
    updated = kernel.store.get("cases", case["id"])
    verified = kernel.store.get("verified_candidates", updated["verified_candidate_id"])
    assert verified is not None
    assert verified["deployed"] is False
    assert verified["status"] == "NOT_DEPLOYED"


def test_verify_candidate_unfixed_is_rejected(tmp_path: Path) -> None:
    kernel = make_kernel(tmp_path)
    case = ready_case(kernel)
    candidate = kernel.submit_candidate(
        principal=ROLE_PRINCIPALS["builder"],
        case_id=case["id"],
        summary="unfixed base",
        diff="",
        files={"lightrag_store.py": base_source()},
        risk="high",
    )
    report = verify_candidate(kernel, case["id"], candidate)
    assert report["verdict"] == "REJECTED"
    assert kernel.store.list("verified_candidates") == []
    updated = kernel.store.get("cases", case["id"])
    assert updated.get("verified_candidate_id") is None
