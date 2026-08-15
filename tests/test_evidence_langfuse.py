from __future__ import annotations

import json

from fastapi.testclient import TestClient

from agentmed.adapters.langfuse import LangfuseUnavailable
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
    issue = {
        "url": "https://github.com/Cinnamon/kotaemon/issues/758",
        "title": "[BUG] LightRAG the qa is not scoped",
        "body": "selecting file A returns file B",
        "number": 758,
    }
    monkeypatch.setattr("agentmed.api.fetch_github_issue", lambda url, token="": issue)
    from agentmed.api import app

    return TestClient(app)


def _open_case(client: TestClient) -> str:
    ingested = client.post(
        "/v1/signals/ingest",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["intake"]},
        json={"url": "https://github.com/Cinnamon/kotaemon/issues/758"},
    )
    assert ingested.status_code == 200, ingested.text
    return ingested.json()["case"]["id"]


def test_evidence_receipt_persists(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    case_id = _open_case(client)
    posted = client.post(
        f"/v1/cases/{case_id}/evidence",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["investigator"]},
        json={
            "kind": "enterprise_monitor",
            "summary": "station skipped; receipt.missing",
            "artifacts": [],
            "missing": ["enterprise_monitor"],
        },
    )
    assert posted.status_code == 200, posted.text
    receipt = posted.json()
    assert receipt["integrity"] == "partial"
    assert receipt["missing"] == ["enterprise_monitor"]
    bundle = client.get(f"/v1/cases/{case_id}/evidence")
    assert bundle.status_code == 200
    ids = [item["id"] for item in bundle.json()["evidence"]]
    assert receipt["id"] in ids


def test_langfuse_ingest_signal_mocked(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    payload = {
        "scores": [
            {"id": "sc-1", "traceId": "tr-1", "name": "accuracy", "value": 0.1, "stringValue": "FAIL"},
        ],
        "traces": [],
    }
    monkeypatch.setattr("agentmed.api._query_langfuse", lambda **_kwargs: payload)
    first = client.post(
        "/v1/signals/ingest-langfuse",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["intake"]},
        json={},
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["status"] == "ok"
    assert body["signal"]["source_type"] == "langfuse_eval"
    assert body["signal"]["source_ref"] == "langfuse:score:sc-1"
    case_id = body["case"]["id"]
    second = client.post(
        "/v1/signals/ingest-langfuse",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["intake"]},
        json={},
    )
    assert second.json()["signal"]["id"] == body["signal"]["id"]
    assert second.json()["case"]["id"] == case_id


def test_langfuse_ingest_unreachable_needs_context(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)

    def boom(**_kwargs):
        raise LangfuseUnavailable("connection refused")

    monkeypatch.setattr("agentmed.api._query_langfuse", boom)
    response = client.post(
        "/v1/signals/ingest-langfuse",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["intake"]},
        json={},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["needs_context"] is True
    assert body["status"] == "NEEDS_CONTEXT"
    assert body["signals"] == []
    assert body["cases"] == []
    assert body["signal"] is None


def test_connect_observability_missing_receipt(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    case_id = _open_case(client)
    response = client.post(
        f"/v1/cases/{case_id}/observability-connect",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["investigator"]},
        json=KOTAEMON_ACCEPT,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "degraded"
    assert "enterprise_monitor_station" in body["evidence"]["missing"]
    assert body["evidence"]["integrity"] == "partial"


def test_verifier_context_withholds_builder_cot(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    case_id = _open_case(client)
    client.post(
        f"/v1/cases/{case_id}/accept",
        headers={"X-AgentMED-Principal": "human:cli"},
        json=KOTAEMON_ACCEPT,
    )
    client.post(
        f"/v1/cases/{case_id}/investigate",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["investigator"]},
    )
    client.post(
        f"/v1/cases/{case_id}/attribute",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["attribution"]},
        json=KOTAEMON_ACCEPT,
    )
    builder = client.get(
        f"/v1/cases/{case_id}/builder-context",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["builder"]},
    )
    assert "instruction" in builder.json()
    client.post(
        f"/v1/cases/{case_id}/candidates",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["builder"]},
        json={"summary": "scope by file_id", "lightrag_store_py": "class LightRAGStore:\n    pass\n"},
    )
    verifier = client.get(
        f"/v1/cases/{case_id}/verifier-context",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["verifier"]},
    )
    payload = verifier.json()
    assert "instruction" not in payload
    assert "lightrag_store_py" not in payload
    assert "withheld" in payload["note"].lower() or "chain-of-thought" in payload["note"].lower()
    assert payload["files"]["lightrag_store.py"].startswith("class LightRAGStore")


def test_verifier_cannot_post_generic_evidence(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    case_id = _open_case(client)
    refused = client.post(
        f"/v1/cases/{case_id}/evidence",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["verifier"]},
        json={
            "kind": "langfuse_traces",
            "summary": "verifier must not use generic evidence POST",
            "artifacts": [{"input": "builder cot"}],
            "missing": [],
        },
    )
    assert refused.status_code == 403


def test_verifier_langfuse_evidence_omits_builder_cot(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    case_id = _open_case(client)
    monkeypatch.setattr(
        "agentmed.adapters.langfuse.fetch_langfuse",
        lambda **_kwargs: {
            "scores": [],
            "traces": [
                {
                    "id": "tr-builder",
                    "name": "builder.propose",
                    "tags": ["builder"],
                    "metadata": {"role": "builder"},
                    "input": "SECRET_BUILDER_COT",
                    "output": "do not leak",
                },
                {
                    "id": "tr-eval",
                    "name": "kotaemon.query",
                    "tags": ["eval", "target_app"],
                    "metadata": {"role": "target_app"},
                },
            ],
        },
    )
    posted = client.post(
        "/v1/evidence/langfuse",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["verifier"]},
        json={"case_id": case_id, "role": "verifier"},
    )
    assert posted.status_code == 200, posted.text
    body = posted.json()
    assert "SECRET_BUILDER_COT" not in json.dumps(body)
    assert "do not leak" not in json.dumps(body)
    ids = {item.get("id") for item in body.get("traces") or []}
    assert "tr-builder" not in ids
    assert "tr-eval" in ids


def test_get_evidence_redacts_builder_fields_for_verifier(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    case_id = _open_case(client)
    client.post(
        f"/v1/cases/{case_id}/accept",
        headers={"X-AgentMED-Principal": "human:cli"},
        json=KOTAEMON_ACCEPT,
    )
    client.post(
        f"/v1/cases/{case_id}/investigate",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["investigator"]},
    )
    client.post(
        f"/v1/cases/{case_id}/attribute",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["attribution"]},
        json=KOTAEMON_ACCEPT,
    )
    client.post(
        f"/v1/cases/{case_id}/candidates",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["builder"]},
        json={
            "summary": "scope by file_id",
            "diff": "SECRET_BUILDER_REASONING",
            "lightrag_store_py": "class LightRAGStore:\n    pass\n",
        },
    )
    as_lead = client.get(f"/v1/cases/{case_id}/evidence")
    assert as_lead.status_code == 200
    lead_candidates = json.dumps(as_lead.json().get("candidates") or [])
    assert "SECRET_BUILDER_REASONING" not in lead_candidates
    assert "---" in lead_candidates and "+++" in lead_candidates
    as_verifier = client.get(
        f"/v1/cases/{case_id}/evidence",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["verifier"]},
    )
    assert as_verifier.status_code == 200
    payload = as_verifier.json()
    assert "audit" not in payload
    assert "diff" not in (payload.get("candidates") or [{}])[0]
    assert "SECRET_BUILDER_REASONING" not in json.dumps(payload.get("candidates") or [])
    assert "withheld" in payload["note"].lower() or "chain-of-thought" in payload["note"].lower()
    assert payload["candidates"][0]["files"]["lightrag_store.py"].startswith("class LightRAGStore")


def test_sanitize_traces_drops_builder_for_verifier() -> None:
    from agentmed.api import _sanitize_trace

    builder = {"id": "1", "name": "builder.propose", "metadata": {"role": "builder"}, "input": "SECRET_COT"}
    eval_trace = {"id": "2", "name": "gate.eval", "metadata": {"role": "verifier"}, "input": "eval-only"}
    assert _sanitize_trace(builder, strip_builder=True) is None
    cleaned = _sanitize_trace(eval_trace, strip_builder=True)
    assert cleaned is not None
    assert cleaned["id"] == "2"
    assert "input" not in cleaned
    assert "SECRET_COT" not in str(cleaned)
