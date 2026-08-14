from __future__ import annotations

from fastapi.testclient import TestClient

from agentmed.adapters.langfuse import LangfuseUnavailable
from agentmed.kernel import ROLE_PRINCIPALS
from agentmed.langfuse_bus import resolve_prompt
from agentmed.workloads.kotaemon import KotaemonAdapter
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


def test_kotaemon_base_episode_leaks() -> None:
    episode = KotaemonAdapter().reproduce_episode()
    assert episode["name"] == "kotaemon.query"
    assert episode["output"]["leaked"] is True
    assert episode["output"]["kept_selected"] is True


def test_kotaemon_golden_episode_does_not_leak() -> None:
    adapter = KotaemonAdapter()
    episode = adapter.reproduce_episode(adapter.golden_files())
    assert episode["output"]["leaked"] is False
    assert episode["output"]["kept_selected"] is True


def test_investigate_queries_langfuse_and_records_traces(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    case_id = _open_case(client)
    monkeypatch.setattr(
        "agentmed.langfuse_bus.fetch_langfuse",
        lambda **_kwargs: {
            "scores": [],
            "traces": [
                {
                    "id": "tr-target",
                    "name": "kotaemon.query",
                    "tags": ["target_app", "eval"],
                    "metadata": {"role": "target_app", "plane": "target_app", "case_id": case_id},
                }
            ],
        },
    )
    client.post(
        f"/v1/cases/{case_id}/accept",
        headers={"X-AgentMED-Principal": "human:cli"},
        json=KOTAEMON_ACCEPT,
    )
    investigated = client.post(
        f"/v1/cases/{case_id}/investigate",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["investigator"]},
    )
    assert investigated.status_code == 200, investigated.text
    body = investigated.json()
    assert body["langfuse"]["queried"] is True
    assert body["langfuse"]["needs_context"] is False
    ids = {item["id"] for item in body["langfuse"]["target_traces"]}
    assert "tr-target" in ids
    kinds = {item["kind"] for item in client.get(f"/v1/cases/{case_id}/evidence").json()["evidence"]}
    assert "langfuse_traces" in kinds
    assert "github_issue" in kinds


def test_investigate_records_queried_gap_when_langfuse_down(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    case_id = _open_case(client)

    def boom(**_kwargs):
        raise LangfuseUnavailable("langfuse host or keys missing")

    monkeypatch.setattr("agentmed.langfuse_bus.fetch_langfuse", boom)
    client.post(
        f"/v1/cases/{case_id}/accept",
        headers={"X-AgentMED-Principal": "human:cli"},
        json=KOTAEMON_ACCEPT,
    )
    investigated = client.post(
        f"/v1/cases/{case_id}/investigate",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["investigator"]},
    )
    assert investigated.status_code == 200, investigated.text
    body = investigated.json()
    assert body["langfuse"]["queried"] is False
    assert "target_app_langfuse_traces" in body["langfuse"]["missing"]
    receipt = body["evidence"]
    assert receipt["kind"] == "langfuse_traces"
    types = {item.get("type") for item in receipt["artifacts"]}
    assert "target_episode" in types
    assert "github_issue" in types


def test_resolve_prompt_falls_back_to_static(monkeypatch) -> None:
    monkeypatch.setattr("agentmed.langfuse_bus.fetch_prompt", lambda **_kwargs: None)
    from agentmed.config import Settings

    resolved = resolve_prompt(Settings(), "builder")
    assert resolved["source"] == "static"
    assert resolved["name"] == "agentmed-playbook-builder"
    assert "Candidate Builder" in (resolved["prompt"] or "")


def test_log_generation_records_prompt_version(monkeypatch) -> None:
    logged: list[dict] = []

    class FakeObs:
        def generation(self, **kwargs):
            logged.append(kwargs)

        def flush(self):
            return None

    monkeypatch.setattr("agentmed.llm_proxy.Observability", lambda settings: FakeObs())
    monkeypatch.setattr(
        "agentmed.langfuse_bus.fetch_prompt",
        lambda **_kwargs: {"name": "agentmed-playbook-builder", "version": 7, "prompt": "sealed"},
    )
    from agentmed.llm_proxy import log_generation

    log_generation(role="builder", model="step-3.7-flash", messages=[], output="ok", case_id="case_x")
    assert logged
    assert logged[0]["metadata"]["prompt_version"] == 7
    assert logged[0]["metadata"]["prompt_source"] == "langfuse"
    assert "case_x" in logged[0]["tags"]
