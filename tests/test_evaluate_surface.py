"""Tests for the CaseLoop exact-versionset evaluate surface.

Covers: token enforcement, registry record reads, envelope shape, and the
upstream call contract (httpx is monkeypatched; no live model traffic).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

P0 = "sha256:258a5e4f0d50fbb4728b82d63f45f45412589a992ca2f2bf553ab7466f0503c7"
P1 = "sha256:4dd5481cc1db92293181c38125df39536809155e11ec43f3f002c1373ac45a67"


def _client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setenv("REQUIRE_LIVE", "false")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")
    monkeypatch.setenv("CASELOOP_EVAL_TOKEN", "eval-secret")
    monkeypatch.setenv("STEP_API_KEY", "step-secret")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/agentmed.db")
    monkeypatch.setenv("AGENTMED_DATA_DIR", str(tmp_path))

    from agentmed.api import app

    return TestClient(app)


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer eval-secret"}


def test_versionset_record_requires_token(tmp_path, monkeypatch) -> None:
    client = _client(monkeypatch, tmp_path)
    resp = client.get("/v2/versionsets/vset_cell_G")
    assert resp.status_code == 401, resp.text


def test_versionset_record_shape(tmp_path, monkeypatch) -> None:
    client = _client(monkeypatch, tmp_path)
    resp = client.get("/v2/versionsets/vset_cell_G", headers=_auth())
    assert resp.status_code == 200, resp.text
    record = resp.json()
    assert record["versionset_id"] == "vset_cell_G"
    assert record["revision"] == 1
    assert record["digest"].startswith("sha256:")
    assert record["content"]["prompt"]["digest"] == P0
    assert record["content"]["kb_manifest"]["manifest_digest"] == P0
    assert record["content"]["model"]["digest"] == P1
    assert record["status"] == "frozen"


def test_versionset_record_unknown_404(tmp_path, monkeypatch) -> None:
    client = _client(monkeypatch, tmp_path)
    resp = client.get("/v2/versionsets/vset_nope", headers=_auth())
    assert resp.status_code == 404, resp.text


def test_evaluate_returns_frozen_digest_envelope(tmp_path, monkeypatch) -> None:
    client = _client(monkeypatch, tmp_path)

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [{"message": {"content": "可以退，7 天无理由。"}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, json, headers):
            assert "chat/completions" in url
            assert json["model"] == "step-3.7-flash"
            assert json["messages"][1]["content"].startswith("我三天前买的蓝牙耳机")
            return FakeResponse()

    import agentmed.evaluate as evaluate

    monkeypatch.setattr(evaluate.httpx, "Client", FakeClient)
    resp = client.post(
        "/v2/versionsets/vset_cell_C/evaluate",
        headers=_auth(),
        json={"message": "我三天前买的蓝牙耳机，现在不想要了，能退吗？"},
    )
    assert resp.status_code == 200, resp.text
    env = resp.json()
    assert env["versionset_id"] == "vset_cell_C"
    assert env["answer"] == "可以退，7 天无理由。"
    assert env["prompt_digest"] == P1
    assert env["kb_manifest_digest"] == P0
    assert env["model_digest"] == P1
    assert env["status"] == "ok"
    assert env["trace_id"].startswith("tr_")
    assert env["request_id"].startswith("req_")


def test_provider_log_roundtrip_and_exactly_one_contract(tmp_path, monkeypatch) -> None:
    client = _client(monkeypatch, tmp_path)
    import agentmed.evaluate as evaluate
    from agentmed.config import load_settings

    settings = load_settings()
    evaluate._append_provider_log(
        settings,
        {
            "request_id": "req_logtest1234567890",
            "status": "ok",
            "trace_id": "tr_logtest1234567890",
            "versionset_id": "vset_cell_C",
            "prompt_digest": P1,
            "kb_manifest_digest": P0,
            "model_digest": P1,
            "answer_digest": "sha256:" + "e" * 64,
        },
    )
    resp = client.get(
        "/v2/logs",
        params={"request_id": "req_logtest1234567890"},
        headers=_auth(),
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["trace_id"] == "tr_logtest1234567890"
    assert items[0]["versionset_id"] == "vset_cell_C"

    missing = client.get(
        "/v2/logs",
        params={"request_id": "req_missing123456789"},
        headers=_auth(),
    )
    assert missing.status_code == 200
    assert missing.json()["items"] == []


def test_provider_log_requires_token(tmp_path, monkeypatch) -> None:
    client = _client(monkeypatch, tmp_path)
    resp = client.get("/v2/logs", params={"request_id": "req_whatever123456"})
    assert resp.status_code == 401, resp.text


def test_evaluate_unknown_versionset_404(tmp_path, monkeypatch) -> None:
    client = _client(monkeypatch, tmp_path)
    resp = client.post(
        "/v2/versionsets/vset_nope/evaluate",
        headers=_auth(),
        json={"message": "hello"},
    )
    assert resp.status_code == 404, resp.text


def _repair_content() -> dict:
    return {
        "prompt": {
            "digest": P0,
            "prompt_id": "prompts/system.md",
            "version": "v1.4.2",
            "content": "你是小智客服。售后政策：我们支持 7 天无理由退货。",
        },
        "kb_manifest": {
            "manifest_digest": P0,
            "version": "1.0.0",
            "entries": [
                {"entry_id": "return-policy-7day", "title": "7 天无理由退货", "content": "我们支持 7 天无理由退货。"},
            ],
        },
        "model": {"digest": P1, "model": "step-3.7-flash", "params": {"temperature": 0.0}},
    }


def test_create_versionset_draft_is_immutable_and_idempotent(tmp_path, monkeypatch) -> None:
    client = _client(monkeypatch, tmp_path)
    content = _repair_content()
    resp = client.post(
        "/v2/versionsets",
        headers={**_auth(), "Idempotency-Key": "repair-ik-0001"},
        json=content,
    )
    assert resp.status_code == 200, resp.text
    record = resp.json()
    assert record["versionset_id"].startswith("vs_")
    assert record["status"] == "draft"
    assert record["revision"] == 1
    assert record["digest"].startswith("sha256:")
    assert record["content"]["prompt"]["digest"] == P0

    # 幂等：同一 content → 同一 versionset
    again = client.post(
        "/v2/versionsets",
        headers=_auth(),
        json=content,
    )
    assert again.status_code == 200
    assert again.json()["versionset_id"] == record["versionset_id"]

    # 不可变记录可读回
    fetched = client.get(f"/v2/versionsets/{record['versionset_id']}", headers=_auth())
    assert fetched.status_code == 200
    assert fetched.json()["digest"] == record["digest"]
    assert fetched.json()["status"] == "draft"


def test_create_versionset_rejects_missing_prompt_text(tmp_path, monkeypatch) -> None:
    client = _client(monkeypatch, tmp_path)
    content = _repair_content()
    content["prompt"]["content"] = "   "
    resp = client.post("/v2/versionsets", headers=_auth(), json=content)
    assert resp.status_code == 422, resp.text


def test_created_draft_evaluates_on_real_path(tmp_path, monkeypatch) -> None:
    client = _client(monkeypatch, tmp_path)
    created = client.post(
        "/v2/versionsets",
        headers=_auth(),
        json=_repair_content(),
    ).json()

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [{"message": {"content": "可以退，7 天无理由。"}}],
                "usage": {"prompt_tokens": 90, "completion_tokens": 18},
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, json, headers):
            assert "chat/completions" in url
            assert json["messages"][0]["content"].startswith("你是小智客服")
            return FakeResponse()

    import agentmed.evaluate as evaluate

    monkeypatch.setattr(evaluate.httpx, "Client", FakeClient)
    resp = client.post(
        f"/v2/versionsets/{created['versionset_id']}/evaluate",
        headers=_auth(),
        json={"message": "能退吗？"},
    )
    assert resp.status_code == 200, resp.text
    env = resp.json()
    assert env["answer"] == "可以退，7 天无理由。"
    assert env["prompt_digest"] == P0
    assert env["model_digest"] == P1
