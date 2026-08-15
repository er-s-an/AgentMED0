from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from agentmed.init_app import draft_system_manifest
from agentmed.kernel import ROLE_PRINCIPALS
from agentmed.mcp_server import FORBIDDEN, INTENTS, dispatch, handle_message
from tests.conftest import KOTAEMON_ACCEPT


def test_review_workspace_exposes_human_actions(tmp_path, monkeypatch) -> None:
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
    page = client.get("/")
    assert page.status_code == 200
    assert "Case Workspace" in page.text
    assert "人确认验收" in page.text
    assert "批准当前工单" in page.text
    assert "不代交对照补丁" in page.text
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
    review = client.get(f"/v1/cases/{case_id}/review")
    assert review.status_code == 200, review.text
    body = review.json()
    assert body["acceptance_spec"]["confirmed_by"].startswith("human:")
    assert body["episode_snapshot"]["sealed"] is True
    assert any(item["assurance"] == "UNKNOWN" for item in body["manifest"]["assurance"])
    apps = client.get("/v1/applications")
    assert apps.status_code == 200
    assert any(item["slug"] == "kotaemon" for item in apps.json()["applications"])


def test_mcp_lists_intents_and_refuses_approvals() -> None:
    listed = handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {item["name"] for item in listed["result"]["tools"]}
    assert names == set(INTENTS)
    assert "approvals.decide" not in names
    forbidden = handle_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "approvals.decide", "arguments": {}},
        }
    )
    assert "error" in forbidden
    assert any(name in forbidden["error"]["message"] for name in FORBIDDEN)


def test_mcp_capabilities_get(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'agentmed.db'}")
    monkeypatch.setenv("AGENTMED_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REQUIRE_LIVE", "false")
    from agentmed.api import app

    client = TestClient(app)
    caps = client.get("/v1/capabilities")
    assert caps.status_code == 200
    assert "cases.get" in caps.json()["intents"]
    assert "approvals.decide" in caps.json()["forbidden"]


def test_mcp_cases_get(tmp_path, monkeypatch) -> None:
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
    payload = dispatch("cases.get", {"case_id": case_id}, client=client)
    body = json.loads(payload["content"][0]["text"])
    assert body["id"] == case_id
    assert body["state"] == "awaiting_acceptance"


def test_init_draft_marks_unknown(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "builder.md").write_text("fix the bug", encoding="utf-8")
    manifest = draft_system_manifest(tmp_path)
    kinds = {item["kind"]: item for item in manifest["components"]}
    assert kinds["python_project"]["assurance"] == "IMMUTABLE_DIGEST"
    assert kinds["model"]["assurance"] == "UNKNOWN"
    assert kinds["index"]["assurance"] == "UNKNOWN"
    assert manifest["complete"] is False
