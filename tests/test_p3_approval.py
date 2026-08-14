from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from agentmed.gate import golden_source
from agentmed.kernel import ROLE_PRINCIPALS, Kernel
from agentmed.release import verify_candidate
from agentmed.store import Store
from tests.helpers import authorize_local_shadow


def make_kernel(tmp_path: Path) -> Kernel:
    return Kernel(Store(f"sqlite:///{tmp_path / 'agentmed.db'}", tmp_path / "data"))


def seed_verified(kernel: Kernel) -> dict:
    app = kernel.ensure_app("kotaemon", "kotaemon", "local")
    signal = kernel.ingest_signal(
        principal=ROLE_PRINCIPALS["intake"],
        source_type="issue",
        source_ref="kotaemon#p3",
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
        manifest={"slug": "kotaemon"},
    )
    kernel.seal_episode(principal=ROLE_PRINCIPALS["investigator"], case_id=case["id"], coverage={"test": True})
    kernel.add_investigation(
        principal=ROLE_PRINCIPALS["attribution"],
        case_id=case["id"],
        hypothesis="file_id",
        conclusion="SUPPORTED",
        uncertainty="test",
    )
    candidate = kernel.submit_candidate(
        principal=ROLE_PRINCIPALS["builder"],
        case_id=case["id"],
        summary="fix",
        diff="",
        files={"lightrag_store.py": golden_source()},
        risk="low",
    )
    report = verify_candidate(kernel, case["id"], candidate)
    assert report["verdict"] == "VERIFIED"
    return kernel.store.get("cases", case["id"])


def test_release_without_approval_is_409(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'agentmed.db'}")
    monkeypatch.setenv("AGENTMED_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REQUIRE_LIVE", "false")
    kernel = make_kernel(tmp_path)
    case = seed_verified(kernel)
    from agentmed.api import app

    client = TestClient(app)
    refused = client.post(
        f"/v1/cases/{case['id']}/release",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["lead"]},
    )
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "NEEDS_RELEASE_PLAN"
    nxt = client.get(f"/v1/cases/{case['id']}/next").json()["next"][0]
    assert nxt["code"] == "REQUEST_SHADOW_PLAN"


def test_work_order_nonce_cannot_be_reused(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'agentmed.db'}")
    monkeypatch.setenv("AGENTMED_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REQUIRE_LIVE", "false")
    kernel = make_kernel(tmp_path)
    case = seed_verified(kernel)
    from agentmed.api import app

    client = TestClient(app)
    authorize_local_shadow(client, case["id"])
    first = client.post(
        f"/v1/cases/{case['id']}/shadow",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["lead"]},
    )
    assert first.status_code == 200, first.text
    second = client.post(
        f"/v1/cases/{case['id']}/release",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["lead"]},
    )
    assert second.status_code == 409
    assert second.json()["detail"]["code"] in {"WORK_ORDER_CONSUMED", "NEEDS_RELEASE_APPROVAL", "NEEDS_RELEASE_PLAN"}
