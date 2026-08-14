from __future__ import annotations

from fastapi.testclient import TestClient

from agentmed.gate import golden_source
from agentmed.kernel import ROLE_PRINCIPALS
from tests.conftest import KOTAEMON_ACCEPT


def _client(tmp_path, monkeypatch) -> TestClient:
    db = tmp_path / "agentmed.db"
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    monkeypatch.setenv("AGENTMED_DATA_DIR", str(data))
    monkeypatch.setenv("REQUIRE_LIVE", "false")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")
    from agentmed.api import app

    return TestClient(app)


def _open_github_case(client: TestClient, monkeypatch) -> str:
    issue = {
        "url": "https://github.com/Cinnamon/kotaemon/issues/758",
        "title": "[BUG] LightRAG the qa is not scoped",
        "body": "selecting file A returns file B",
        "number": 758,
    }
    monkeypatch.setattr("agentmed.api.fetch_github_issue", lambda url, token="": issue)
    ingested = client.post(
        "/v1/signals/ingest",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["intake"]},
        json={"url": issue["url"]},
    )
    assert ingested.status_code == 200, ingested.text
    return ingested.json()["case"]["id"]


def test_evidence_post_persists(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    case_id = _open_github_case(client, monkeypatch)
    posted = client.post(
        f"/v1/cases/{case_id}/evidence",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["investigator"]},
        json={
            "kind": "langfuse",
            "summary": "no live traces",
            "artifacts": [{"type": "note", "ref": "local"}],
            "missing": ["target_app_langfuse_traces"],
        },
    )
    assert posted.status_code == 200, posted.text
    receipt = posted.json()
    assert receipt["kind"] == "langfuse"
    assert receipt["case_id"] == case_id
    assert receipt["missing"] == ["target_app_langfuse_traces"]
    exported = client.get(f"/v1/cases/{case_id}/evidence")
    assert exported.status_code == 200, exported.text
    evidence_ids = [item["id"] for item in exported.json()["evidence"]]
    assert receipt["id"] in evidence_ids


def test_ingest_langfuse_empty_needs_context(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "agentmed.adapters.langfuse.fetch_langfuse",
        lambda **kwargs: {"scores": [], "traces": []},
    )
    response = client.post(
        "/v1/signals/ingest-langfuse",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["intake"]},
        json={},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["needs_context"] is True
    assert body["missing"] == ["langfuse_traces"]
    assert body["signal"] is None
    assert body["case"] is None
    listed = client.get("/v1/cases")
    assert listed.json()["cases"] == []


def test_ingest_langfuse_failed_score_opens_case_idempotent(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    payload = {
        "scores": [
            {
                "id": "scr-758",
                "traceId": "tr-eval-1",
                "name": "file_scope",
                "value": 0.1,
                "comment": "retrieval leaked file B",
                "tags": ["eval"],
            }
        ],
        "traces": [
            {
                "id": "tr-builder",
                "name": "builder.generate",
                "tags": ["builder"],
                "input": "secret builder cot",
                "output": "do not ingest this",
                "metadata": {"role": "builder"},
            }
        ],
    }
    monkeypatch.setattr("agentmed.adapters.langfuse.fetch_langfuse", lambda **kwargs: payload)
    first = client.post(
        "/v1/signals/ingest-langfuse",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["intake"]},
        json={"failed_only": True},
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["case"] is not None
    assert body["signal"]["source_type"] == "langfuse_eval"
    assert body["signal"]["source_ref"] == "langfuse:score:scr-758"
    assert "secret builder cot" not in (body["signal"].get("body") or "")
    assert "do not ingest this" not in (body["signal"].get("body") or "")
    case_id = body["case"]["id"]
    second = client.post(
        "/v1/signals/ingest-langfuse",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["intake"]},
        json={"failed_only": True},
    )
    assert second.status_code == 200, second.text
    assert second.json()["case"]["id"] == case_id
    assert second.json()["signal"]["id"] == body["signal"]["id"]
    listed = client.get("/v1/cases")
    assert len(listed.json()["cases"]) == 1


def test_langfuse_traces_verifier_omits_builder_span(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    case_id = _open_github_case(client, monkeypatch)
    payload = {
        "scores": [],
        "traces": [
            {
                "id": "tr-builder",
                "name": "builder.propose",
                "tags": ["builder"],
                "metadata": {"role": "builder"},
                "input": "builder prompt",
                "output": "builder cot",
            },
            {
                "id": "tr-eval",
                "name": "kotaemon.query",
                "tags": ["eval", "target_app"],
                "metadata": {"role": "target_app"},
            },
        ],
    }
    monkeypatch.setattr("agentmed.adapters.langfuse.fetch_langfuse", lambda **kwargs: payload)
    investigator = client.get(
        f"/v1/cases/{case_id}/langfuse-traces",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["investigator"]},
        params={"role": "investigator"},
    )
    assert investigator.status_code == 200, investigator.text
    inv_ids = {item["id"] for item in investigator.json()["traces"]}
    assert "tr-builder" in inv_ids
    assert "tr-eval" in inv_ids
    verifier = client.get(
        f"/v1/cases/{case_id}/langfuse-traces",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["verifier"]},
        params={"role": "verifier"},
    )
    assert verifier.status_code == 200, verifier.text
    ver_ids = {item["id"] for item in verifier.json()["traces"]}
    assert "tr-builder" not in ver_ids
    assert "tr-eval" in ver_ids
    for item in verifier.json()["traces"]:
        assert "builder cot" not in str(item)
        assert item.get("output") is None or "builder" not in str(item.get("output"))


def test_draft_pr_refuses_unverified_case(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    case_id = _open_github_case(client, monkeypatch)
    refused = client.post(
        f"/v1/cases/{case_id}/draft-pr",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["lead"]},
    )
    assert refused.status_code == 400, refused.text
    assert "VerifiedCandidate" in refused.text or "VERIFIED" in refused.text

    accepted = client.post(
        f"/v1/cases/{case_id}/accept",
        headers={"X-AgentMED-Principal": "human:cli"},
        json=KOTAEMON_ACCEPT,
    )
    assert accepted.status_code == 200, accepted.text
    client.post(
        f"/v1/cases/{case_id}/investigate",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["investigator"]},
    )
    client.post(
        f"/v1/cases/{case_id}/attribute",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["attribution"]},
        json={},
    )
    submitted = client.post(
        f"/v1/cases/{case_id}/candidates",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["builder"]},
        json={"summary": "scope by file_id", "lightrag_store_py": golden_source()},
    )
    assert submitted.status_code == 200, submitted.text
    still = client.post(
        f"/v1/cases/{case_id}/draft-pr",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["lead"]},
    )
    assert still.status_code == 400, still.text
    verified = client.post(
        f"/v1/cases/{case_id}/verify",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["verifier"]},
    )
    assert verified.status_code == 200, verified.text
    drafted = client.post(
        f"/v1/cases/{case_id}/draft-pr",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["lead"]},
    )
    assert drafted.status_code == 200, drafted.text
    assert drafted.json()["reused"] is False
    patch = drafted.json()["patch"]
    assert patch.endswith("draft.patch")
    again = client.post(
        f"/v1/cases/{case_id}/draft-pr",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["controller"]},
    )
    assert again.status_code == 200, again.text
    assert again.json()["reused"] is True
