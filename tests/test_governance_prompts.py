from __future__ import annotations

from fastapi.testclient import TestClient

from agentmed.kernel import ROLE_PRINCIPALS
from agentmed.llm_proxy import infer_role, redact
from agentmed.prompt_catalog import harvest_prompts
from agentmed.team.dispatch import rewrite_env_key


def test_harvest_includes_worker_soul_and_skips_vendor_langfuse() -> None:
    records = harvest_prompts()
    names = {item["name"] for item in records}
    assert "agentmed-playbook-builder" in names
    assert "agentmed-playbook-verifier" in names
    assert "agentmed-worker-builder-soul" in names
    assert "agentmed-worker-intake-identity" in names
    assert "agentmed-manager-soul-appendix" in names
    assert "agentmed-skill-propose-candidate" in names
    assert "agentmed-skill-provision-langfuse" in names
    assert not any("langfuse" in name and "skill-langfuse" in name for name in names)
    vendor = [item for item in records if "skills/langfuse" in str(item.get("source") or "")]
    assert vendor == []
    builder = next(item for item in records if item["name"] == "agentmed-worker-builder-soul")
    assert "CandidateRevision" in builder["prompt"]
    assert "sk-lf-" not in json_dump_all(records)


def json_dump_all(records) -> str:
    return "".join(str(item.get("prompt") or "") for item in records)


def test_infer_role_from_system_identity() -> None:
    builder = infer_role(
        [{"role": "system", "content": "- Name: builder\n- Principal: agent:builder\nPropose a patch"}]
    )
    verifier = infer_role(
        [{"role": "system", "content": "- Name: verifier\nYou are AgentMED Independent Verifier"}]
    )
    manager = infer_role(
        [{"role": "system", "content": "You are the Manager of the AgentMED quality team. Kernel HTTP is source of truth."}]
    )
    header = infer_role([{"role": "user", "content": "hi"}], {"X-AgentMED-Principal": "agent:intake"})
    assert builder == "builder"
    assert verifier == "verifier"
    assert manager == "manager"
    assert header == "intake"
    target = infer_role(
        [{"role": "user", "content": "hi"}],
        {"User-Agent": "OpenClaw/2026.5.18", "Authorization": "Bearer agentmed-kernel-proxy"},
    )
    assert target == "target_app"


def test_redact_keys_and_langfuse_secrets() -> None:
    cleaned = redact(
        {
            "authorization": "Bearer super-secret",
            "messages": [{"role": "user", "content": "pk-lf-MUST-HIDE and sk-lf-MUST-HIDE too"}],
        }
    )
    dumped = str(cleaned)
    assert "super-secret" not in dumped
    assert "pk-lf-MUST-HIDE" not in dumped
    assert "sk-lf-MUST-HIDE" not in dumped
    assert "[redacted]" in dumped


def test_rewrite_env_key_only_changes_target(tmp_path) -> None:
    path = tmp_path / "agentteams-manager.env"
    path.write_text(
        "AGENTTEAMS_LLM_API_KEY=must-not-appear-in-return\n"
        "AGENTTEAMS_OPENAI_BASE_URL=https://api.stepfun.com/step_plan/v1\n",
        encoding="utf-8",
    )
    result = rewrite_env_key(
        path, "AGENTTEAMS_OPENAI_BASE_URL", "http://host.docker.internal:8088/v1"
    )
    assert result["changed"] is True
    text = path.read_text(encoding="utf-8")
    assert "http://host.docker.internal:8088/v1" in text
    assert "must-not-appear-in-return" in text
    assert result.get("secret") is None
    dumped = str(result)
    assert "must-not-appear-in-return" not in dumped


def test_retarget_llm_defaults_on(monkeypatch, tmp_path) -> None:
    env = tmp_path / "agentteams-manager.env"
    env.write_text("AGENTTEAMS_OPENAI_BASE_URL=https://example.invalid/v1\n", encoding="utf-8")
    monkeypatch.delenv("AGENTMED_RETARGET_LLM", raising=False)
    monkeypatch.setattr("agentmed.team.dispatch._env_file", lambda: env)
    from agentmed.config import Settings
    from agentmed.team.dispatch import retarget_agentteams_llm

    updated = retarget_agentteams_llm(Settings())
    assert updated["status"] == "updated"
    assert "8088/v1" in env.read_text(encoding="utf-8")

    monkeypatch.setenv("AGENTMED_RETARGET_LLM", "0")
    skipped = retarget_agentteams_llm(Settings())
    assert skipped["status"] == "skipped"


def test_governance_prompts_endpoint(tmp_path, monkeypatch) -> None:
    db = tmp_path / "agentmed.db"
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    monkeypatch.setenv("AGENTMED_DATA_DIR", str(data))
    monkeypatch.setenv("REQUIRE_LIVE", "false")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")
    from agentmed.api import app

    client = TestClient(app)
    listed = client.get(
        "/v1/governance/prompts",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["lead"]},
    )
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["count"] >= 20
    names = body["names"]
    assert "agentmed-worker-builder-soul" in names
    prompts = {item["name"]: item for item in body["prompts"]}
    assert "CandidateRevision" in prompts["agentmed-worker-builder-soul"]["prompt"]

    verifier = client.get(
        "/v1/governance/prompts",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["verifier"]},
    )
    assert verifier.status_code == 200, verifier.text
    v_prompts = {item["name"]: item for item in verifier.json()["prompts"]}
    builder = v_prompts["agentmed-worker-builder-soul"]
    assert builder.get("prompt") in (None, "")
    assert builder.get("redacted") is True


def test_llm_proxy_forwards_and_logs_role(tmp_path, monkeypatch) -> None:
    db = tmp_path / "agentmed.db"
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    monkeypatch.setenv("AGENTMED_DATA_DIR", str(data))
    monkeypatch.setenv("REQUIRE_LIVE", "false")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")
    monkeypatch.setenv("STEP_API_KEY", "kernel-held-step-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.stepfun.com/step_plan/v1")

    logged: list[dict] = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "id": "chatcmpl-test",
                "model": "step-3.7-flash",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "candidate sealed"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4},
            }

    class FakeClient:
        last: dict = {}

        def __init__(self, *args, **kwargs):
            del args, kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, json=None, headers=None, **kwargs):
            FakeClient.last = {"url": url, "json": json, "headers": headers}
            return FakeResponse()

    monkeypatch.setattr("agentmed.llm_proxy.httpx.Client", FakeClient)
    monkeypatch.setattr("agentmed.llm_proxy.log_generation", lambda **kwargs: logged.append(kwargs))

    from agentmed.api import app

    client = TestClient(app)
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer worker-must-not-be-used"},
        json={
            "model": "step-3.7-flash",
            "messages": [
                {"role": "system", "content": "- Name: builder\nPropose the smallest candidate."},
                {"role": "user", "content": "fix kotaemon #758"},
            ],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["choices"][0]["message"]["content"] == "candidate sealed"
    assert FakeClient.last["url"].endswith("/chat/completions")
    assert "stepfun.com" in FakeClient.last["url"]
    assert FakeClient.last["headers"]["Authorization"] == "Bearer kernel-held-step-key"
    assert logged and logged[0]["role"] == "builder"
    assert logged[0]["output"] == "candidate sealed"


def test_langfuse_traces_exclude_agentmed_governance(tmp_path, monkeypatch) -> None:
    db = tmp_path / "agentmed.db"
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    monkeypatch.setenv("AGENTMED_DATA_DIR", str(data))
    monkeypatch.setenv("REQUIRE_LIVE", "false")
    issue = {
        "url": "https://github.com/Cinnamon/kotaemon/issues/758",
        "title": "[BUG] LightRAG the qa is not scoped",
        "body": "selecting file A returns file B",
        "number": 758,
    }
    monkeypatch.setattr("agentmed.api.fetch_github_issue", lambda url, token="": issue)
    payload = {
        "scores": [],
        "traces": [
            {
                "id": "tr-agentmed-builder",
                "name": "agentmed.builder.llm",
                "tags": ["agentmed-governance", "builder"],
                "metadata": {"product": "agentmed", "role": "builder", "plane": "governance"},
                "input": "secret builder cot",
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
    from agentmed.api import app

    client = TestClient(app)
    ingested = client.post(
        "/v1/signals/ingest",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["intake"]},
        json={"url": issue["url"]},
    )
    case_id = ingested.json()["case"]["id"]
    target = client.get(
        f"/v1/cases/{case_id}/langfuse-traces",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["investigator"]},
    )
    assert target.status_code == 200, target.text
    ids = {item["id"] for item in target.json()["traces"]}
    assert "tr-eval" in ids
    assert "tr-agentmed-builder" not in ids

    gov = client.get(
        "/v1/governance/traces",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["lead"]},
    )
    assert gov.status_code == 200, gov.text
    gov_ids = {item["id"] for item in gov.json()["traces"]}
    assert "tr-agentmed-builder" in gov_ids
    assert "tr-eval" not in gov_ids

    verifier = client.get(
        "/v1/governance/traces",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["verifier"]},
    )
    assert verifier.status_code == 200, verifier.text
    ver_ids = {item["id"] for item in verifier.json()["traces"]}
    assert "tr-agentmed-builder" not in ver_ids
    assert "secret builder cot" not in verifier.text
