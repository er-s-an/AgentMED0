from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from agentmed.gate import golden_source
from agentmed.kernel import ROLE_PRINCIPALS, Kernel
from agentmed.release import verify_candidate
from agentmed.store import Store
from tests.conftest import KOTAEMON_ACCEPT


def make_kernel(tmp_path: Path) -> Kernel:
    return Kernel(Store(f"sqlite:///{tmp_path / 'agentmed.db'}", tmp_path / "data"))


def test_inconclusive_stays_investigating(tmp_path: Path) -> None:
    kernel = make_kernel(tmp_path)
    app = kernel.ensure_app("kotaemon", "kotaemon", "local")
    signal = kernel.ingest_signal(
        principal=ROLE_PRINCIPALS["intake"],
        source_type="issue",
        source_ref="kotaemon#p1",
        title="leak",
        body="leak",
        application_id=app["id"],
        raw={},
    )
    case = kernel.open_case(principal=ROLE_PRINCIPALS["lead"], signal=signal, application=app)
    kernel.confirm_acceptance(
        principal=ROLE_PRINCIPALS["human"],
        case_id=case["id"],
        expected_behavior="scoped",
        badcase_input="a vs b",
        judge="eval",
    )
    kernel.bind_version_snapshot(
        principal=ROLE_PRINCIPALS["investigator"],
        case_id=case["id"],
        manifest={"slug": "kotaemon", "commit": "abc"},
    )
    kernel.add_investigation(
        principal=ROLE_PRINCIPALS["attribution"],
        case_id=case["id"],
        hypothesis="maybe",
        conclusion="INCONCLUSIVE",
        uncertainty="need traces",
    )
    updated = kernel.store.get("cases", case["id"])
    assert updated["state"] == "investigating"
    nxt = kernel.next_actions(case["id"])[0]
    assert nxt["code"] == "NEEDS_EVIDENCE"
    assert nxt["role"] == "investigator"


def test_snapshot_exposes_unknown_assurance(tmp_path: Path) -> None:
    kernel = make_kernel(tmp_path)
    app = kernel.ensure_app("kotaemon", "kotaemon", "local")
    signal = kernel.ingest_signal(
        principal=ROLE_PRINCIPALS["intake"],
        source_type="issue",
        source_ref="kotaemon#p1b",
        title="leak",
        body="leak",
        application_id=app["id"],
        raw={},
    )
    case = kernel.open_case(principal=ROLE_PRINCIPALS["lead"], signal=signal, application=app)
    snap = kernel.bind_version_snapshot(
        principal=ROLE_PRINCIPALS["investigator"],
        case_id=case["id"],
        manifest={"slug": "kotaemon", "commit": "abc"},
    )
    kinds = {item["kind"]: item["assurance"] for item in snap["manifest"]["components"]}
    assert kinds["upstream_commit"] == "PROVIDER_VERSION"
    assert kinds["model"] == "UNKNOWN"


def test_verify_without_episode_snapshot_is_409(tmp_path, monkeypatch) -> None:
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
    kernel = make_kernel(tmp_path)
    app_row = kernel.ensure_app("kotaemon", "kotaemon", "local")
    signal = kernel.ingest_signal(
        principal=ROLE_PRINCIPALS["intake"],
        source_type="issue",
        source_ref="kotaemon#no-episode",
        title="leak",
        body="leak",
        application_id=app_row["id"],
        raw={},
    )
    case = kernel.open_case(principal=ROLE_PRINCIPALS["lead"], signal=signal, application=app_row)
    kernel.confirm_acceptance(
        principal=ROLE_PRINCIPALS["human"],
        case_id=case["id"],
        expected_behavior="scoped",
        badcase_input="a vs b",
        judge="eval",
    )
    kernel.bind_version_snapshot(
        principal=ROLE_PRINCIPALS["investigator"],
        case_id=case["id"],
        manifest={"slug": "kotaemon"},
    )
    kernel.add_investigation(
        principal=ROLE_PRINCIPALS["attribution"],
        case_id=case["id"],
        hypothesis="file_id",
        conclusion="SUPPORTED",
        uncertainty="test",
    )
    kernel.submit_candidate(
        principal=ROLE_PRINCIPALS["builder"],
        case_id=case["id"],
        summary="fix",
        diff="",
        files={"lightrag_store.py": golden_source()},
        risk="low",
    )
    verified = client.post(
        f"/v1/cases/{case['id']}/verify",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["verifier"]},
    )
    assert verified.status_code == 409
    assert verified.json()["detail"]["code"] == "NEEDS_EPISODE_SNAPSHOT"


def test_add_evidence_does_not_mutate_sealed_episode(tmp_path: Path) -> None:
    kernel = make_kernel(tmp_path)
    app = kernel.ensure_app("kotaemon", "kotaemon", "local")
    signal = kernel.ingest_signal(
        principal=ROLE_PRINCIPALS["intake"],
        source_type="issue",
        source_ref="kotaemon#seal",
        title="leak",
        body="leak",
        application_id=app["id"],
        raw={},
    )
    case = kernel.open_case(principal=ROLE_PRINCIPALS["lead"], signal=signal, application=app)
    sealed = kernel.seal_episode(
        principal=ROLE_PRINCIPALS["investigator"],
        case_id=case["id"],
        coverage={"first": True},
        extra_missing=["target_app_langfuse_traces"],
    )
    kernel.add_evidence(
        principal=ROLE_PRINCIPALS["investigator"],
        case_id=case["id"],
        kind="note",
        summary="later",
        artifacts=[],
        missing=["new-missing"],
    )
    again = kernel.seal_episode(principal=ROLE_PRINCIPALS["investigator"], case_id=case["id"])
    assert again["id"] == sealed["id"]
    assert again["digest"] == sealed["digest"]
    assert again["missing"] == ["target_app_langfuse_traces"]


def test_investigate_http_seals_and_shows_unknown(tmp_path, monkeypatch) -> None:
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
    investigated = client.post(
        f"/v1/cases/{case_id}/investigate",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["investigator"]},
    )
    assert investigated.status_code == 200, investigated.text
    components = investigated.json()["snapshot"]["manifest"]["components"]
    assert any(item["assurance"] == "UNKNOWN" for item in components)
    assert investigated.json()["episode_snapshot"]["sealed"] is True
    bundle = client.get(f"/v1/cases/{case_id}/evidence").json()
    assert bundle["episode_snapshot"]["id"] == investigated.json()["episode_snapshot"]["id"]
