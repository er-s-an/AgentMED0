from __future__ import annotations

from fastapi.testclient import TestClient

from agentmed.gate import golden_source
from agentmed.kernel import ROLE_PRINCIPALS


def test_kernel_http_ingest_verify_close(tmp_path, monkeypatch) -> None:
    db = tmp_path / "agentmed.db"
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    monkeypatch.setenv("AGENTMED_DATA_DIR", str(data))
    monkeypatch.setenv("REQUIRE_LIVE", "false")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")

    issue = {
        "url": "https://github.com/Cinnamon/kotaemon/issues/758",
        "title": "[BUG] LightRAG the qa is not scoped",
        "body": "selecting file A returns file B",
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
    assert ingested.status_code == 200, ingested.text
    case_id = ingested.json()["case"]["id"]
    accepted = client.post(
        f"/v1/cases/{case_id}/accept",
        headers={"X-AgentMED-Principal": "human:cli"},
        json={},
    )
    assert accepted.status_code == 200, accepted.text
    investigated = client.post(
        f"/v1/cases/{case_id}/investigate",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["investigator"]},
    )
    assert investigated.status_code == 200, investigated.text
    attributed = client.post(
        f"/v1/cases/{case_id}/attribute",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["attribution"]},
        json={},
    )
    assert attributed.status_code == 200, attributed.text
    context = client.get(
        f"/v1/cases/{case_id}/builder-context",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["builder"]},
    )
    assert "del file_id" in context.json()["lightrag_store_py"]
    submitted = client.post(
        f"/v1/cases/{case_id}/candidates",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["builder"]},
        json={"summary": "scope by file_id", "lightrag_store_py": golden_source()},
    )
    assert submitted.status_code == 200, submitted.text
    verified = client.post(
        f"/v1/cases/{case_id}/verify",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["verifier"]},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["verdict"] == "VERIFIED"
    released = client.post(
        f"/v1/cases/{case_id}/release",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["lead"]},
    )
    assert released.status_code == 200, released.text
    closed = client.post(
        f"/v1/cases/{case_id}/close",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["curator"]},
        json={"summary": "scoped retrieval"},
    )
    assert closed.status_code == 200, closed.text
    shown = client.get(f"/v1/cases/{case_id}")
    assert shown.json()["state"] == "closed"
