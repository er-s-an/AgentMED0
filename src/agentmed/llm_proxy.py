from __future__ import annotations

import json
import re
from typing import Any

import httpx
from fastapi.responses import JSONResponse, StreamingResponse

from agentmed.config import Settings, load_settings
from agentmed.observability import Observability

ROLE_MARKERS = (
    "quality-officer",
    "investigator",
    "attribution",
    "builder",
    "verifier",
    "curator",
    "intake",
    "manager",
)
_SECRET_RE = re.compile(
    r"(?i)(sk-lf-[A-Za-z0-9_-]+|pk-lf-[A-Za-z0-9_-]+|sk-[A-Za-z0-9]{16,}|Bearer\s+\S+)"
)
_SECRET_KEYS = frozenset(
    {"authorization", "api_key", "apikey", "secret", "secret_key", "token", "password"}
)
_LOOP_HOSTS = ("127.0.0.1", "localhost", "0.0.0.0", "host.docker.internal")


class LLMProxyError(RuntimeError):
    pass


def redact(value: Any) -> Any:
    if isinstance(value, str):
        return _SECRET_RE.sub("[redacted]", value)
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in _SECRET_KEYS:
                out[key] = "[redacted]"
            else:
                out[key] = redact(item)
        return out
    return value


def infer_role(messages: list[Any], headers: dict[str, str] | None = None) -> str:
    headers = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    for key in ("x-agentmed-role", "x-agentmed-principal"):
        raw = headers.get(key, "").strip().lower()
        if not raw:
            continue
        raw = raw.removeprefix("agent:")
        for role in ROLE_MARKERS:
            if role == raw or raw.endswith(role):
                return role
    blob = "\n".join(
        str(item.get("content") or "")
        for item in messages
        if isinstance(item, dict) and item.get("role") == "system"
    )
    for role in ROLE_MARKERS:
        if f"Name: {role}" in blob or f"name: {role}" in blob.lower():
            return role
        if f"Principal: agent:{role}" in blob:
            return role
    lowered = blob.lower()
    if "you are the manager of the agentmed quality team" in lowered:
        return "manager"
    if "agentmed (product loop)" in lowered:
        return "manager"
    return "unknown"


def upstream_chat_url(settings: Settings) -> str:
    base = (settings.openai_base_url or "").rstrip("/")
    if not base:
        raise LLMProxyError("OPENAI_BASE_URL missing")
    port = str(settings.kernel_api_port)
    if port in base and any(host in base for host in _LOOP_HOSTS):
        raise LLMProxyError("OPENAI_BASE_URL points at Kernel; refusing LLM proxy loop")
    return f"{base}/chat/completions"


def log_generation(
    *,
    role: str,
    model: str,
    messages: Any,
    output: Any,
    usage: dict[str, Any] | None = None,
    source: str = "kernel_llm_proxy",
) -> None:
    settings = load_settings()
    obs = Observability(settings)
    obs.generation(
        name=f"agentmed.{role}.llm",
        model=model,
        input_text=redact(messages),
        output_text=redact(output),
        usage=usage or {},
        metadata={
            "role": role,
            "product": "agentmed",
            "plane": "governance",
            "source": source,
        },
        tags=["agentmed-governance", "agentmed", role],
    )
    obs.flush()


def _usage(payload: dict[str, Any]) -> dict[str, Any]:
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    return {
        "input": usage.get("prompt_tokens"),
        "output": usage.get("completion_tokens"),
    }


def _content_from_sse(raw: bytes) -> str:
    texts: list[str] = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            obj = json.loads(data)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        for choice in obj.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
            if isinstance(delta.get("content"), str):
                texts.append(delta["content"])
            message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
            if isinstance(message.get("content"), str):
                texts.append(message["content"])
    return "".join(texts)


def proxy_chat(payload: dict[str, Any], headers: dict[str, str] | None = None) -> JSONResponse | StreamingResponse:
    settings = load_settings()
    if not settings.openai_api_key:
        return JSONResponse(
            {"error": {"message": "Kernel STEP_API_KEY missing", "type": "agentmed_llm_proxy"}},
            status_code=503,
        )
    try:
        url = upstream_chat_url(settings)
    except LLMProxyError as exc:
        return JSONResponse(
            {"error": {"message": str(exc), "type": "agentmed_llm_proxy"}},
            status_code=503,
        )
    messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
    role = infer_role(messages, headers)
    model = str(payload.get("model") or settings.agentmed_model)
    upstream_headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    stream = bool(payload.get("stream"))
    timeout = httpx.Timeout(300.0, connect=10.0)
    if stream:
        def generate():
            chunks: list[bytes] = []
            try:
                with httpx.Client(timeout=timeout) as client:
                    with client.stream("POST", url, json=payload, headers=upstream_headers) as response:
                        for chunk in response.iter_bytes():
                            chunks.append(chunk)
                            yield chunk
            finally:
                raw = b"".join(chunks)
                try:
                    log_generation(
                        role=role,
                        model=model,
                        messages=messages,
                        output=_content_from_sse(raw) or raw.decode("utf-8", errors="replace")[:8000],
                        source="kernel_llm_proxy",
                    )
                except Exception:
                    pass

        return StreamingResponse(generate(), media_type="text/event-stream")

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, json=payload, headers=upstream_headers)
    except Exception as exc:
        return JSONResponse(
            {"error": {"message": f"{type(exc).__name__}", "type": "agentmed_llm_proxy"}},
            status_code=502,
        )
    try:
        body = response.json()
    except Exception:
        body = {"error": {"message": "upstream returned non-JSON", "type": "agentmed_llm_proxy"}}
    output = ""
    if isinstance(body, dict):
        choices = body.get("choices") or []
        if choices and isinstance(choices[0], dict):
            message = choices[0].get("message") if isinstance(choices[0].get("message"), dict) else {}
            output = message.get("content") or str(message.get("tool_calls") or "")
        log_generation(
            role=role,
            model=str(body.get("model") or model),
            messages=messages,
            output=output,
            usage=_usage(body) if isinstance(body, dict) else {},
            source="kernel_llm_proxy",
        )
    return JSONResponse(body, status_code=response.status_code)


def models_payload(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or load_settings()
    return {
        "object": "list",
        "data": [
            {
                "id": settings.agentmed_model,
                "object": "model",
                "owned_by": "agentmed-kernel-proxy",
            }
        ],
    }
