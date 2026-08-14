"""stdio MCP gateway. Maps intents onto Kernel HTTP. No approvals or execute."""

from __future__ import annotations

import json
import sys
from typing import Any

import httpx

from agentmed.config import load_settings

INTENTS = (
    "capabilities.get",
    "signals.submit",
    "cases.get",
    "cases.timeline",
    "candidates.submit",
    "evidence.get",
    "gate-reports.get",
)
FORBIDDEN = ("approvals.decide", "shadow.execute", "release.execute")


def _kernel_url() -> str:
    settings = load_settings()
    return f"http://127.0.0.1:{settings.kernel_api_port}"


def _tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "capabilities.get",
            "description": "List AgentMED gateway intents. Approvals and execute are not exposed.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "signals.submit",
            "description": "Ingest a GitHub issue URL as a Signal and open or reuse a Case.",
            "inputSchema": {
                "type": "object",
                "properties": {"url": {"type": "string"}, "slug": {"type": "string"}},
                "required": ["url"],
            },
        },
        {
            "name": "cases.get",
            "description": "Read authoritative Case state.",
            "inputSchema": {
                "type": "object",
                "properties": {"case_id": {"type": "string"}},
                "required": ["case_id"],
            },
        },
        {
            "name": "cases.timeline",
            "description": "Export the Case evidence bundle (timeline).",
            "inputSchema": {
                "type": "object",
                "properties": {"case_id": {"type": "string"}},
                "required": ["case_id"],
            },
        },
        {
            "name": "candidates.submit",
            "description": "Submit sealed candidate files as agent:builder.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "case_id": {"type": "string"},
                    "summary": {"type": "string"},
                    "files": {"type": "object"},
                    "diff": {"type": "string"},
                    "risk": {"type": "string"},
                },
                "required": ["case_id", "summary", "files"],
            },
        },
        {
            "name": "evidence.get",
            "description": "Read Case evidence. Verifier principal redacts Builder CoT.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "case_id": {"type": "string"},
                    "principal": {"type": "string"},
                },
                "required": ["case_id"],
            },
        },
        {
            "name": "gate-reports.get",
            "description": "Read GateReports for a Case.",
            "inputSchema": {
                "type": "object",
                "properties": {"case_id": {"type": "string"}},
                "required": ["case_id"],
            },
        },
    ]


def _ok(data: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, default=str)}]}


def dispatch(name: str, arguments: dict[str, Any], *, client: Any = None, base: str | None = None) -> dict[str, Any]:
    if name in FORBIDDEN:
        raise PermissionError(f"{name} is not exposed on the MCP gateway")
    if name not in INTENTS:
        raise KeyError(name)
    owns = client is None
    if client is None:
        client = httpx.Client(timeout=30.0)
        base = base or _kernel_url()
    else:
        base = (base or "").rstrip("/")
    try:
        if name == "capabilities.get":
            return _ok(client.get(f"{base}/v1/capabilities").json())
        if name == "signals.submit":
            return _ok(
                client.post(
                    f"{base}/v1/signals/ingest",
                    headers={"X-AgentMED-Principal": "agent:intake"},
                    json={"url": arguments["url"], "slug": arguments.get("slug")},
                ).json()
            )
        case_id = str(arguments.get("case_id") or "")
        if name == "cases.get":
            return _ok(client.get(f"{base}/v1/cases/{case_id}").json())
        if name == "cases.timeline":
            return _ok(client.get(f"{base}/v1/cases/{case_id}/evidence").json())
        if name == "candidates.submit":
            return _ok(
                client.post(
                    f"{base}/v1/cases/{case_id}/candidates",
                    headers={"X-AgentMED-Principal": "agent:builder"},
                    json={
                        "summary": arguments.get("summary"),
                        "files": arguments.get("files") or {},
                        "diff": arguments.get("diff") or "",
                        "risk": arguments.get("risk") or "low",
                    },
                ).json()
            )
        if name == "evidence.get":
            principal = arguments.get("principal") or "agent:investigator"
            return _ok(
                client.get(
                    f"{base}/v1/cases/{case_id}/evidence",
                    headers={"X-AgentMED-Principal": principal},
                ).json()
            )
        if name == "gate-reports.get":
            bundle = client.get(f"{base}/v1/cases/{case_id}/evidence").json()
            return _ok({"case_id": case_id, "gate_reports": bundle.get("gate_reports") or []})
    finally:
        if owns:
            client.close()
    raise KeyError(name)


def _reply(msg_id: Any, result: Any | None = None, error: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": msg_id}
    if error:
        payload["error"] = error
    else:
        payload["result"] = result
    return payload


def handle_message(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    msg_id = message.get("id")
    if method == "initialize":
        return _reply(
            msg_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "agentmed", "version": "0.1.0"},
            },
        )
    if method == "notifications/initialized" or method == "initialized":
        return None
    if method == "tools/list":
        return _reply(msg_id, {"tools": _tools()})
    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        try:
            return _reply(msg_id, dispatch(name, arguments))
        except Exception as exc:
            return _reply(msg_id, error={"code": -32000, "message": str(exc)})
    if msg_id is None:
        return None
    return _reply(msg_id, error={"code": -32601, "message": f"unknown method {method}"})


def serve_stdio() -> None:
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            sys.stdout.write(json.dumps(_reply(None, error={"code": -32700, "message": str(exc)})) + "\n")
            sys.stdout.flush()
            continue
        reply = handle_message(message)
        if reply is None:
            continue
        sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def main() -> None:
    serve_stdio()


if __name__ == "__main__":
    main()
