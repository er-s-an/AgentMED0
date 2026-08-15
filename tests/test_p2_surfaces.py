from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from agentmed.gate import golden_source
from agentmed.kernel import ROLE_PRINCIPALS, Kernel
from agentmed.release import verify_candidate
from agentmed.store import Store
from agentmed.workloads import get_adapter, list_adapters
from tests.conftest import KOTAEMON_ACCEPT


def make_kernel(tmp_path: Path) -> Kernel:
    return Kernel(Store(f"sqlite:///{tmp_path / 'agentmed.db'}", tmp_path / "data"))


def seed_ready(kernel: Kernel, *, slug: str = "kotaemon", source_ref: str = "kotaemon#p2") -> dict:
    app = kernel.ensure_app(slug, slug, "local")
    signal = kernel.ingest_signal(
        principal=ROLE_PRINCIPALS["intake"],
        source_type="issue",
        source_ref=source_ref,
        title="bad outcome",
        body="repro",
        application_id=app["id"],
        raw={},
    )
    case = kernel.open_case(principal=ROLE_PRINCIPALS["lead"], signal=signal, application=app)
    kernel.confirm_acceptance(
        principal=ROLE_PRINCIPALS["human"],
        case_id=case["id"],
        expected_behavior="fixed",
        badcase_input="repro",
        judge="eval",
    )
    kernel.bind_version_snapshot(
        principal=ROLE_PRINCIPALS["investigator"],
        case_id=case["id"],
        manifest=get_adapter(slug).snapshot_manifest(source_ref),
    )
    kernel.seal_episode(principal=ROLE_PRINCIPALS["investigator"], case_id=case["id"], coverage={"test": True})
    kernel.add_investigation(
        principal=ROLE_PRINCIPALS["attribution"],
        case_id=case["id"],
        hypothesis="root cause",
        conclusion="SUPPORTED",
        uncertainty="test",
    )
    return kernel.store.get("cases", case["id"])


def test_kotaemon_gate_reports_harness_and_upstream(tmp_path: Path) -> None:
    kernel = make_kernel(tmp_path)
    case = seed_ready(kernel)
    adapter = get_adapter("kotaemon")
    candidate = kernel.submit_candidate(
        principal=ROLE_PRINCIPALS["builder"],
        case_id=case["id"],
        summary="scope",
        diff="",
        files=adapter.golden_files(),
        risk="low",
    )
    report = verify_candidate(kernel, case["id"], candidate)
    assert report["verdict"] == "VERIFIED"
    assert set(report["evidence"]["surfaces"]) >= {"harness", "upstream", "holdout"}
    by_surface = {row["surface"]: row for row in report["evidence"]["by_surface"]}
    assert by_surface["harness"]["candidate_fail_to_pass"] is True
    assert by_surface["upstream"]["candidate_fail_to_pass"] is True
    assert by_surface["holdout"]["candidate_fail_to_pass"] is True


def test_holdout_is_hidden_from_builder_context(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'agentmed.db'}")
    monkeypatch.setenv("AGENTMED_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REQUIRE_LIVE", "false")
    issue = {
        "url": "https://github.com/Cinnamon/kotaemon/issues/758",
        "title": "scoped",
        "body": "leak",
        "number": 758,
    }
    monkeypatch.setattr("agentmed.api.fetch_github_issue", lambda url, token="": issue)
    from agentmed.api import app

    client = TestClient(app)
    ingested = client.post(
        "/v1/signals/ingest",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["intake"]},
        json={"url": issue["url"]},
    )
    case_id = ingested.json()["case"]["id"]
    client.post(f"/v1/cases/{case_id}/accept", headers={"X-AgentMED-Principal": "human:cli"}, json=KOTAEMON_ACCEPT)
    client.post(
        f"/v1/cases/{case_id}/investigate",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["investigator"]},
    )
    context = client.get(
        f"/v1/cases/{case_id}/builder-context",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["builder"]},
    )
    assert context.status_code == 200, context.text
    blob = context.text
    assert "eval-holdout" not in blob
    assert "gamma-policy" not in blob


def test_failed_regression_probe_rejects(tmp_path: Path) -> None:
    kernel = make_kernel(tmp_path)
    first = seed_ready(kernel, source_ref="kotaemon#reg-1")
    adapter = get_adapter("kotaemon")
    first_candidate = kernel.submit_candidate(
        principal=ROLE_PRINCIPALS["builder"],
        case_id=first["id"],
        summary="first",
        diff="",
        files=adapter.golden_files(),
        risk="low",
    )
    verify_candidate(kernel, first["id"], first_candidate)
    kernel.close_with_asset(
        principal=ROLE_PRINCIPALS["curator"],
        case_id=first["id"],
        summary="keep a probe that the next bad candidate will fail",
        probes=["eval/test_file_scope.py"],
        lessons="persist file_id",
    )
    second = seed_ready(kernel, source_ref="kotaemon#reg-2")
    bad = kernel.submit_candidate(
        principal=ROLE_PRINCIPALS["builder"],
        case_id=second["id"],
        summary="broken",
        diff="",
        files=adapter.base_files(),
        risk="high",
    )
    report = verify_candidate(kernel, second["id"], bad)
    assert report["verdict"] == "REJECTED"
    ran = report["evidence"]["regression_probes"]
    assert ran
    assert any(item["passed"] is False for item in ran)


def test_langgraph_triplet_and_workloads_list() -> None:
    adapter = get_adapter("langgraph")
    assert adapter.run_eval(adapter.base_files())["passed"] is False
    assert adapter.run_eval(adapter.golden_files())["passed"] is True
    assert adapter.run_eval(adapter.known_bad_files())["passed"] is False
    slugs = {spec.slug for spec in list_adapters()}
    assert slugs >= {"kotaemon", "langgraph"}


def test_langgraph_http_loop(tmp_path: Path) -> None:
    kernel = make_kernel(tmp_path)
    case = seed_ready(
        kernel,
        slug="langgraph",
        source_ref="https://github.com/langchain-ai/langgraph/issues/7684",
    )
    adapter = get_adapter("langgraph")
    candidate = kernel.submit_candidate(
        principal=ROLE_PRINCIPALS["builder"],
        case_id=case["id"],
        summary="numeric compare",
        diff="",
        files=adapter.golden_files(),
        risk="low",
    )
    report = verify_candidate(kernel, case["id"], candidate)
    assert report["verdict"] == "VERIFIED"
    assert report["evidence"]["workload"] == "langgraph"
    verified = kernel.store.get("verified_candidates", kernel._case(case["id"])["verified_candidate_id"])
    assert verified["status"] == "NOT_DEPLOYED"
