from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn

from agentmed.adapters.langfuse import LangfuseUnavailable
from agentmed.kernel import ROLE_PRINCIPALS

REPO = Path(__file__).resolve().parents[1]
SKILLS = REPO / "agentteams" / "skills"

ISSUE = {
    "url": "https://github.com/Cinnamon/kotaemon/issues/758",
    "title": "[BUG] LightRAG the qa is not scoped",
    "body": "selecting file A returns file B",
    "number": 758,
}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def kernel_http(tmp_path, monkeypatch):
    db = tmp_path / "agentmed.db"
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    monkeypatch.setenv("AGENTMED_DATA_DIR", str(data))
    monkeypatch.setenv("REQUIRE_LIVE", "false")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")
    langfuse_state: dict = {"payload": {"scores": [], "traces": []}, "unavailable": False}

    def fake_fetch(**_kwargs):
        if langfuse_state["unavailable"]:
            raise LangfuseUnavailable("connection refused")
        return langfuse_state["payload"]

    monkeypatch.setattr("agentmed.api.fetch_github_issue", lambda url, token="": ISSUE)
    monkeypatch.setattr("agentmed.adapters.langfuse.fetch_langfuse", fake_fetch)
    monkeypatch.setattr("agentmed.api._query_langfuse", fake_fetch)

    from agentmed.api import app

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 8
    while time.time() < deadline:
        if server.started:
            try:
                if httpx.get(f"{url}/health", timeout=0.3).status_code == 200:
                    break
            except Exception:
                pass
        time.sleep(0.05)
    else:
        server.should_exit = True
        raise RuntimeError("kernel HTTP did not start")
    try:
        yield {"url": url, "langfuse": langfuse_state}
    finally:
        server.should_exit = True
        thread.join(timeout=2)


def _run_skill(skill: str, args: list[str], *, kernel_url: str, principal: str, extra_env: dict | None = None):
    script = SKILLS / skill / "scripts" / "run.sh"
    env = {
        **os.environ,
        "AGENTMED_KERNEL_URL": kernel_url,
        "AGENTMED_PRINCIPAL": principal,
        "LANGFUSE_SECRET_KEY": "leak-me-now-secret",
        "LANGFUSE_PUBLIC_KEY": "leak-me-now-public",
    }
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(script), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        cwd=str(script.parent),
    )


def _ingest(kernel_url: str) -> str:
    response = httpx.post(
        f"{kernel_url}/v1/signals/ingest",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["intake"]},
        json={"url": ISSUE["url"]},
        timeout=15,
    )
    assert response.status_code == 200, response.text
    return response.json()["case"]["id"]


def _stdout_json(completed: subprocess.CompletedProcess[str]) -> dict:
    text = (completed.stdout or "").strip()
    assert text, f"empty stdout: stderr={completed.stderr!r}"
    return json.loads(text.splitlines()[-1] if text.splitlines() else text)


def test_draft_pr_refuses_unverified_case(kernel_http) -> None:
    case_id = _ingest(kernel_http["url"])
    result = _run_skill(
        "draft-pr",
        [case_id],
        kernel_url=kernel_http["url"],
        principal=ROLE_PRINCIPALS["lead"],
    )
    assert result.returncode != 0
    combined = (result.stdout or "") + (result.stderr or "")
    assert "VerifiedCandidate" in combined or "VERIFIED" in combined or "unverified" in combined.lower()


def test_connect_observability_missing_station(kernel_http) -> None:
    case_id = _ingest(kernel_http["url"])
    result = _run_skill(
        "connect-observability",
        [case_id],
        kernel_url=kernel_http["url"],
        principal=ROLE_PRINCIPALS["investigator"],
    )
    assert result.returncode == 0, result.stderr
    body = _stdout_json(result)
    missing = body.get("missing") or (body.get("receipt") or {}).get("missing") or []
    assert "enterprise_monitor_station" in missing
    assert all(token not in json.dumps(body) for token in ("0.42", "99.9%", "forged_metric"))


def test_query_langfuse_investigator_needs_context(kernel_http) -> None:
    case_id = _ingest(kernel_http["url"])
    kernel_http["langfuse"]["payload"] = {"scores": [], "traces": []}
    result = _run_skill(
        "query-langfuse",
        [case_id, "investigator"],
        kernel_url=kernel_http["url"],
        principal=ROLE_PRINCIPALS["investigator"],
    )
    assert result.returncode == 0, result.stderr
    body = _stdout_json(result)
    assert body.get("needs_context") is True
    assert body.get("traces") == []
    assert "span-invented" not in json.dumps(body)


def test_query_langfuse_verifier_omits_builder_cot(kernel_http) -> None:
    case_id = _ingest(kernel_http["url"])
    kernel_http["langfuse"]["payload"] = {
        "scores": [],
        "traces": [
            {
                "id": "tr-builder",
                "name": "builder.propose",
                "tags": ["builder"],
                "metadata": {"role": "builder"},
                "input": "builder cot",
                "output": "secret builder reasoning",
            },
            {
                "id": "tr-eval",
                "name": "kotaemon.query",
                "tags": ["eval", "target_app"],
                "metadata": {"role": "target_app"},
            },
        ],
    }
    result = _run_skill(
        "query-langfuse",
        [case_id, "verifier"],
        kernel_url=kernel_http["url"],
        principal=ROLE_PRINCIPALS["verifier"],
    )
    assert result.returncode == 0, result.stderr
    text = (result.stdout or "") + (result.stderr or "")
    assert "builder cot" not in text
    assert "secret builder reasoning" not in text
    body = _stdout_json(result)
    ids = {item.get("id") for item in body.get("traces") or []}
    assert "tr-builder" not in ids
    if ids:
        assert "tr-eval" in ids


def test_ingest_langfuse_empty_needs_context(kernel_http) -> None:
    kernel_http["langfuse"]["payload"] = {"scores": [], "traces": []}
    result = _run_skill(
        "ingest-langfuse",
        [],
        kernel_url=kernel_http["url"],
        principal=ROLE_PRINCIPALS["intake"],
    )
    assert result.returncode == 0, result.stderr
    body = _stdout_json(result)
    assert body.get("needs_context") is True
    listed = httpx.get(f"{kernel_http['url']}/v1/cases", timeout=10)
    assert listed.json()["cases"] == []


def test_ingest_langfuse_failed_score_opens_case(kernel_http) -> None:
    kernel_http["langfuse"]["payload"] = {
        "scores": [
            {
                "id": "scr-skill",
                "traceId": "tr-eval-1",
                "name": "file_scope",
                "value": 0.1,
                "comment": "retrieval leaked file B",
                "tags": ["eval"],
            }
        ],
        "traces": [],
    }
    result = _run_skill(
        "ingest-langfuse",
        [],
        kernel_url=kernel_http["url"],
        principal=ROLE_PRINCIPALS["intake"],
    )
    assert result.returncode == 0, result.stderr
    body = _stdout_json(result)
    signal = body.get("signal") or {}
    assert signal.get("source_type") == "langfuse_eval"
    assert signal.get("source_ref") == "langfuse:score:scr-skill"
    assert body.get("case")


def test_provision_langfuse_needs_context_without_secrets(kernel_http) -> None:
    kernel_http["langfuse"]["unavailable"] = True
    result = _run_skill(
        "provision-langfuse",
        [],
        kernel_url=kernel_http["url"],
        principal=ROLE_PRINCIPALS["investigator"],
    )
    assert result.returncode == 0, result.stderr
    text = (result.stdout or "") + (result.stderr or "")
    assert "leak-me-now-secret" not in text
    assert "leak-me-now-public" not in text
    body = _stdout_json(result)
    assert body.get("needs_context") is True or body.get("status") == "NEEDS_CONTEXT"
    dumped = json.dumps(body)
    assert "LANGFUSE_PUBLIC_KEY" in dumped or "public_key_ref" in dumped or body.get("needs_context") is True
