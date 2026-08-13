from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from typing import Any

import httpx

from agentmed.config import Settings
from agentmed.gate import base_source, run_eval

DOCKER_BIN = "/usr/local/bin/docker"
DEMO_ISSUE = "https://github.com/Cinnamon/kotaemon/issues/758"


class LiveStackError(RuntimeError):
    """Raised when a required live process is missing or unhealthy."""


@dataclass
class Probe:
    name: str
    ok: bool
    detail: str
    process: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _docker() -> str:
    if os.path.isfile(DOCKER_BIN):
        return DOCKER_BIN
    found = shutil.which("docker")
    if found:
        return found
    return DOCKER_BIN


def probe_github(settings: Settings, signal_url: str = DEMO_ISSUE) -> Probe:
    from agentmed.adapters.github import fetch_github_issue

    try:
        issue = fetch_github_issue(signal_url, settings.github_token)
    except Exception as exc:
        return Probe("github", False, f"{type(exc).__name__}: {exc}", "api.github.com")
    title = issue.get("title") or ""
    number = issue.get("number")
    return Probe(
        "github",
        True,
        f"issue #{number} title={title[:80]!r}",
        "api.github.com",
    )


def probe_gate() -> Probe:
    try:
        result = run_eval(base_source())
    except Exception as exc:
        return Probe("gate", False, f"{type(exc).__name__}: {exc}", "pytest eval")
    if result["passed"]:
        return Probe("gate", False, "base workload unexpectedly passed; Gate cannot reproduce #758", "pytest eval")
    return Probe(
        "gate",
        True,
        f"base eval fails as required (returncode={result['returncode']})",
        "pytest eval",
    )


def probe_langfuse(settings: Settings) -> Probe:
    url = settings.langfuse_host.rstrip("/") + "/api/public/health"
    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        return Probe("langfuse", False, "LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY missing", url)
    docker = _docker()
    inspect = subprocess.run(
        [docker, "inspect", "-f", "{{.State.Running}}", "langfuse-langfuse-web-1"],
        capture_output=True,
        text=True,
        timeout=8,
    )
    container_up = inspect.returncode == 0 and inspect.stdout.strip() == "true"
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.get(url)
        if response.status_code == 200:
            payload = response.json() if "json" in response.headers.get("content-type", "") else {}
            status = payload.get("status") or "ok"
            version = payload.get("version") or ""
            return Probe("langfuse", True, f"status={status} version={version}", "docker:langfuse-web")
        http_detail = f"HTTP {response.status_code}"
    except Exception as exc:
        http_detail = f"{type(exc).__name__}: {exc}"
    if container_up:
        return Probe(
            "langfuse",
            True,
            f"container running; health HTTP degraded ({http_detail})",
            "docker:langfuse-web",
        )
    return Probe("langfuse", False, f"container down; {http_detail}", url)


def probe_model(settings: Settings) -> Probe:
    if not settings.openai_api_key:
        return Probe(
            "model",
            False,
            "STEP_API_KEY / OPENAI_API_KEY missing; Plan endpoint needs a StepFun key",
            settings.openai_base_url,
        )
    url = settings.openai_base_url.rstrip("/") + "/chat/completions"
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                url,
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.agentmed_model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 8,
                },
            )
        if response.status_code in {200, 201}:
            data = response.json()
            model = data.get("model") or settings.agentmed_model
            return Probe("model", True, f"chat.completions ok model={model}", url)
        snippet = response.text[:240].replace(settings.openai_api_key, "***")
        if response.status_code in {401, 403}:
            return Probe(
                "model",
                False,
                f"Plan endpoint reachable but key rejected (HTTP {response.status_code}). Set STEP_API_KEY for https://api.stepfun.com/step_plan/v1",
                url,
            )
        return Probe("model", False, f"HTTP {response.status_code} {snippet}", url)
    except Exception as exc:
        return Probe("model", False, f"{type(exc).__name__}: {exc}", url)


def probe_agentteams(settings: Settings) -> Probe:
    docker = _docker()
    names: list[str] = []
    try:
        proc = subprocess.run(
            [docker, "ps", "--filter", "name=agentteams", "--format", "{{.Names}} {{.Status}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            names = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    except Exception as exc:
        names = []
        docker_err = f"{type(exc).__name__}: {exc}"
    else:
        docker_err = proc.stderr.strip() if proc.returncode else ""

    has_controller = any("agentteams-controller" in n for n in names)
    has_manager = any("agentteams-manager" in n for n in names)
    endpoints = {
        "element": settings.agentteams_element.rstrip("/"),
        "gateway": settings.agentteams_gateway.rstrip("/"),
        "dashboard": settings.agentteams_dashboard.rstrip("/"),
    }
    http_ok: list[str] = []
    try:
        with httpx.Client(timeout=4.0, follow_redirects=True) as client:
            for label, base in endpoints.items():
                try:
                    response = client.get(base)
                    if response.status_code < 500:
                        http_ok.append(f"{label}:{response.status_code}")
                except Exception:
                    continue
    except Exception:
        pass

    if has_controller and has_manager:
        extra = f"containers={len(names)} http=[{', '.join(http_ok) or 'none'}]"
        return Probe("agentteams", True, extra, "docker:agentteams-controller+manager")
    detail_parts = [
        f"controller={'yes' if has_controller else 'no'}",
        f"manager={'yes' if has_manager else 'no'}",
        f"http=[{', '.join(http_ok) or 'none'}]",
    ]
    if docker_err:
        detail_parts.append(docker_err[:160])
    if not names:
        detail_parts.append("no agentteams-* containers; run scripts/live-stack.sh")
    return Probe("agentteams", False, "; ".join(detail_parts), "docker:agentteams")


def probe_all(settings: Settings, *, signal_url: str = DEMO_ISSUE) -> list[Probe]:
    return [
        probe_agentteams(settings),
        probe_langfuse(settings),
        probe_model(settings),
        probe_gate(),
        probe_github(settings, signal_url),
    ]


def as_report(probes: list[Probe]) -> dict[str, Any]:
    return {
        "ok": all(item.ok for item in probes),
        "probes": [item.as_dict() for item in probes],
    }


def assert_live(settings: Settings, *, signal_url: str = DEMO_ISSUE) -> dict[str, Any]:
    probes = probe_all(settings, signal_url=signal_url)
    report = as_report(probes)
    if not report["ok"]:
        failed = [item.name for item in probes if not item.ok]
        lines = [f"{item.name}: {'OK' if item.ok else 'FAIL'} — {item.detail}" for item in probes]
        raise LiveStackError(
            "live stack incomplete (" + ", ".join(failed) + "):\n" + "\n".join(lines)
        )
    return report
