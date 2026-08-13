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


def _start_server(app, host: str, port: int):
    try:
        import uvicorn
    except ImportError:
        pytest.skip("uvicorn is required for skill script HTTP tests")
    config = uvicorn.Config(app, host=host, port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return server, thread


@pytest.fixture
def kernel_url(tmp_path, monkeypatch) -> str:
    db = tmp_path / "agentmed.db"
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    monkeypatch.setenv("AGENTMED_DATA_DIR", str(data))
    monkeypatch.setenv("REQUIRE_LIVE", "false")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")

    from agentmed.api import app

    monkeypatch.setattr("agentmed.api.fetch_github_issue", lambda url, token="": ISSUE)
    monkeypatch.setattr(
        "agentmed.adapters.langfuse.fetch_langfuse",
        lambda **_kwargs: {"scores": [], "traces": []},
    )

    port = _free_port()
    server, thread = _start_server(app, "127.0.0.1", port)
    url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 8
    while time.time() < deadline:
        try:
            if httpx.get(f"{url}/health", timeout=0.3).status_code == 200:
                break
        except Exception:
            time.sleep(0.05)
    else:
        server.should_exit = True
        raise RuntimeError("kernel HTTP did not start")
    try:
        yield url
    finally:
        server.should_exit = True
        thread.join(timeout=2)


def run_skill(
    skill: str,
    args: list[str],
    kernel_url: str,
    principal: str,
    extra_env: dict | None = None,
) -> subprocess.CompletedProcess[str]:
    script = SKILLS / skill / "scripts" / "run.sh"
    env = os.environ.copy()
    env["AGENTMED_KERNEL_URL"] = kernel_url
    env["AGENTMED_PRINCIPAL"] = principal
    env.pop("MONITOR_URL", None)
    env.pop("MONITOR_MCP_URL", None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(script), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=20,
        cwd=str(script.parent),
    )


def _stdout_json(completed: subprocess.CompletedProcess[str]) -> dict:
    text = (completed.stdout or "").strip()
    assert text, f"empty stdout: stderr={completed.stderr!r} code={completed.returncode}"
    decoder = json.JSONDecoder()
    start = text.find("{")
    assert start >= 0, f"no JSON in stdout={completed.stdout!r} stderr={completed.stderr!r}"
    payload, _ = decoder.raw_decode(text[start:])
    assert isinstance(payload, dict), payload
    return payload


def _open_case(kernel_url: str) -> str:
    result = run_skill(
        "ingest-signal",
        [ISSUE["url"]],
        kernel_url,
        ROLE_PRINCIPALS["intake"],
    )
    assert result.returncode == 0, result.stderr
    body = _stdout_json(result)
    case_id = (body.get("case") or {}).get("id")
    assert case_id, body
    return case_id


def test_ingest_signal_opens_case(kernel_url: str) -> None:
    result = run_skill(
        "ingest-signal",
        [ISSUE["url"]],
        kernel_url,
        ROLE_PRINCIPALS["intake"],
    )
    assert result.returncode == 0, result.stderr
    body = _stdout_json(result)
    assert body.get("case", {}).get("id")


def test_connect_observability_degraded_without_monitor(kernel_url: str) -> None:
    case_id = _open_case(kernel_url)
    result = run_skill(
        "connect-observability",
        [case_id],
        kernel_url,
        ROLE_PRINCIPALS["investigator"],
        extra_env={"MONITOR_URL": "", "MONITOR_MCP_URL": ""},
    )
    assert result.returncode == 0, result.stderr
    body = _stdout_json(result)
    assert body.get("status") == "degraded"
    receipt = body.get("receipt") or {}
    missing = [str(item) for item in (receipt.get("missing") or body.get("missing") or [])]
    dumped = json.dumps(body)
    assert any("enterprise_monitor" in item for item in missing) or "missing" in dumped.lower()
    assert body.get("metrics") in (None, {}, [])
    lower = dumped.lower()
    assert "forged" not in lower
    for token in ("0.42", "99.9%", "forged_metric"):
        assert token not in dumped


def test_query_langfuse_investigator_needs_context(kernel_url: str) -> None:
    case_id = _open_case(kernel_url)
    result = run_skill(
        "query-langfuse",
        [case_id, "investigator"],
        kernel_url,
        ROLE_PRINCIPALS["investigator"],
    )
    assert result.returncode == 0, result.stderr
    body = _stdout_json(result)
    assert body.get("needs_context") is True
    assert body.get("traces") == []
    dumped = json.dumps(body)
    assert "span-invented" not in dumped
    assert "invent" not in dumped.lower() or "do not invent" in dumped.lower()


def test_query_langfuse_verifier_needs_context_without_403(kernel_url: str) -> None:
    case_id = _open_case(kernel_url)
    result = run_skill(
        "query-langfuse",
        [case_id, "verifier"],
        kernel_url,
        ROLE_PRINCIPALS["verifier"],
    )
    assert result.returncode == 0, result.stderr
    combined = f"{result.stdout or ''}{result.stderr or ''}"
    assert "HTTP 403" not in combined
    assert "status_code=403" not in combined
    body = _stdout_json(result)
    assert body.get("needs_context") is True
    # Verifier must not require posting evidence to succeed.
    assert body.get("traces") in ([], None)


def test_provision_langfuse_intake_hides_secrets(kernel_url: str) -> None:
    secret = "sk-lf-MUST-NOT-PRINT"
    public = "pk-lf-MUST-NOT-PRINT"
    result = run_skill(
        "provision-langfuse",
        [],
        kernel_url,
        ROLE_PRINCIPALS["intake"],
        extra_env={"LANGFUSE_SECRET_KEY": secret, "LANGFUSE_PUBLIC_KEY": public},
    )
    assert result.returncode == 0, result.stderr
    combined = f"{result.stdout or ''}{result.stderr or ''}"
    assert secret not in combined
    assert public not in combined
    body = _stdout_json(result)
    status = str(body.get("status") or "")
    assert body.get("needs_context") is True or status in {"NEEDS_CONTEXT", "ok"}
    dumped = json.dumps(body)
    assert secret not in dumped
    assert public not in dumped


def test_ingest_langfuse_empty_needs_context(kernel_url: str) -> None:
    result = run_skill(
        "ingest-langfuse",
        [],
        kernel_url,
        ROLE_PRINCIPALS["intake"],
    )
    assert result.returncode == 0, result.stderr
    body = _stdout_json(result)
    assert body.get("needs_context") is True
    assert body.get("case") in (None, {}, [])
    nested = (body.get("kernel") or {}).get("case")
    assert nested in (None, {}, [])
    listed = httpx.get(f"{kernel_url}/v1/cases", timeout=10)
    assert listed.status_code == 200, listed.text
    assert listed.json()["cases"] == []


def test_draft_pr_refuses_unverified_case(kernel_url: str) -> None:
    case_id = _open_case(kernel_url)
    result = run_skill(
        "draft-pr",
        [case_id],
        kernel_url,
        ROLE_PRINCIPALS["lead"],
    )
    assert result.returncode != 0
