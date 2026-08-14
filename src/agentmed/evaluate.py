"""Exact-versionset evaluate surface for the governed app (xiaozhi-customer-service).

CaseLoop's eval-harness probes the governed app through two read-only routes:

- POST /v2/versionsets/{versionset_id}/evaluate  -> one probe against the exact
  immutable VersionSet (prompt/kb/model components bound by the registry).
- GET  /v2/versionsets/{versionset_id}           -> the VersionSet record.

The registry (workloads/xiaozhi-customer-service/registry.json) binds the frozen
CaseLoop component identities (control-plane component-revision record digests)
to concrete runtime content.  Every evaluation goes through the real model path
(stepfun via OPENAI_BASE_URL) and is logged to Langfuse with role caseloop-eval,
so each cell run leaves a real trace.

Auth: the request must carry Authorization: Bearer <CASELOOP_EVAL_TOKEN>.
The endpoint fails closed (503) when the token is not provisioned.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException

from agentmed.config import Settings, load_settings
from agentmed.llm_proxy import LLMProxyError, upstream_chat_url
from agentmed.observability import Observability

REPO_ROOT = Path(__file__).resolve().parents[2]


def registry_path(settings: Settings) -> Path:
    path = Path(settings.evaluate_registry_path)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def load_registry(settings: Settings) -> dict[str, Any]:
    path = registry_path(settings)
    if not path.exists():
        raise HTTPException(
            status_code=503,
            detail=f"evaluate registry not provisioned: {path}",
        )
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=503, detail=f"evaluate registry unreadable: {exc}") from exc
    if registry.get("schema_version") != "1.0":
        raise HTTPException(status_code=503, detail="evaluate registry schema_version mismatch")
    return registry


def require_eval_token(settings: Settings, authorization: str | None) -> None:
    if not settings.caseloop_eval_token:
        raise HTTPException(status_code=503, detail="evaluate surface not provisioned (CASELOOP_EVAL_TOKEN unset)")
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not token or token != settings.caseloop_eval_token:
        raise HTTPException(status_code=401, detail="invalid evaluate token")


def _kb_text(entries: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for entry in entries:
        title = str(entry.get("title") or entry.get("entry_id") or "").strip()
        content = str(entry.get("content") or "").strip()
        if title and content:
            blocks.append("### " + title + chr(10) + content)
    return "\n\n".join(blocks)


def compose_system(prompt_component: dict[str, Any], kb_component: dict[str, Any]) -> str:
    prompt_text = str(prompt_component.get("content") or "").strip()
    kb_entries = kb_component.get("entries") or []
    kb_block = _kb_text(kb_entries)
    if kb_block:
        return prompt_text + "\n\n## 知识库资料（产品参数/物流规则）\n" + kb_block
    return prompt_text


def get_versionset_record(settings: Settings, versionset_id: str) -> dict[str, Any]:
    registry = load_registry(settings)
    record = registry.get("versionset_records", {}).get(versionset_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"versionset {versionset_id} not found in evaluate registry")
    return record


def provider_log_path(settings: Settings) -> Path:
    data_dir = Path(settings.agentmed_data_dir)
    if not data_dir.is_absolute():
        data_dir = REPO_ROOT / data_dir
    return data_dir / "evaluate_log.jsonl"


def _append_provider_log(settings: Settings, entry: dict[str, Any]) -> None:
    """Append one provider-log entry (immutable JSONL; CaseLoop get_log reads it)."""
    path = provider_log_path(settings)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + chr(10))
    except OSError:
        # Persistence failure must not fail the evaluation itself; the control
        # plane's get_log then answers 404 and the trial is rejected fail-closed.
        pass


def get_provider_log(settings: Settings, request_id: str) -> dict[str, Any]:
    path = provider_log_path(settings)
    items: list[dict[str, Any]] = []
    if path.exists():
        try:
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if row.get("request_id") == request_id:
                        items.append(row)
        except OSError as exc:
            raise HTTPException(status_code=503, detail=f"provider log unreadable: {exc}") from exc
    return {"items": items}


def evaluate_versionset(
    settings: Settings,
    versionset_id: str,
    message: str,
) -> dict[str, Any]:
    """Run one probe against the exact immutable VersionSet on the real model path."""
    registry = load_registry(settings)
    cell = registry.get("cells", {}).get(versionset_id)
    if cell is None:
        raise HTTPException(status_code=404, detail=f"versionset {versionset_id} not in evaluate cells")
    components = registry.get("components") or {}
    prompt_component = components.get(cell[0])
    kb_component = components.get(cell[1])
    model_component = components.get(cell[2])
    if prompt_component is None or kb_component is None or model_component is None:
        raise HTTPException(status_code=503, detail=f"evaluate registry missing component for {versionset_id}")
    if model_component.get("kind") != "model":
        raise HTTPException(status_code=503, detail=f"evaluate registry model binding invalid for {versionset_id}")

    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="Kernel STEP_API_KEY missing")
    try:
        url = upstream_chat_url(settings)
    except LLMProxyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    system = compose_system(prompt_component, kb_component)
    model_name = str(model_component.get("model") or settings.agentmed_model)
    params = dict(model_component.get("params") or {})
    payload: dict[str, Any] = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": message},
        ],
        "stream": False,
    }
    payload.update(params)

    upstream_headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    timeout = httpx.Timeout(120.0, connect=10.0)
    # Provider-side resilience: transient upstream failures and empty completions
    # are retried up to 3 attempts; a persistent empty completion surfaces as 502
    # so the eval-harness's retry-with-backoff layer takes over.  The answer is
    # never fabricated: status stays "ok" only for a real non-empty completion.
    answer = ""
    usage: dict[str, Any] = {}
    for attempt in range(1, 4):
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(url, json=payload, headers=upstream_headers)
        except httpx.HTTPError as exc:
            if attempt == 3:
                raise HTTPException(status_code=502, detail=f"upstream evaluate failed: {type(exc).__name__}") from exc
            continue
        if response.status_code != 200:
            if attempt == 3:
                raise HTTPException(
                    status_code=502,
                    detail=f"upstream evaluate HTTP {response.status_code}: {response.text[:300]}",
                )
            continue
        try:
            body = response.json()
        except ValueError as exc:
            if attempt == 3:
                raise HTTPException(status_code=502, detail="upstream returned non-JSON") from exc
            continue
        choices = body.get("choices") or []
        if choices and isinstance(choices[0], dict):
            message_obj = choices[0].get("message") if isinstance(choices[0].get("message"), dict) else {}
            answer = str(message_obj.get("content") or "")
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        if answer:
            break
    if not answer:
        raise HTTPException(status_code=502, detail="upstream returned empty completion after 3 attempts")

    request_id = "req_" + uuid.uuid4().hex[:24]
    trace_id = "tr_" + uuid.uuid4().hex[:24]
    try:
        obs = Observability(settings)
        obs.generation(
            name="xiaozhi.caseloop-eval.llm",
            model=model_name,
            input_text={"system": system[:4000], "user": message},
            output_text=answer[:8000],
            usage={"input": usage.get("prompt_tokens"), "output": usage.get("completion_tokens")},
            metadata={
                "role": "caseloop-eval",
                "product": "xiaozhi-customer-service",
                "plane": "governed-app",
                "source": "versionset_evaluate",
                "versionset_id": versionset_id,
                "prompt_digest": prompt_component.get("digest"),
                "kb_manifest_digest": kb_component.get("digest"),
                "model_digest": model_component.get("digest"),
            },
            tags=["caseloop", "caseloop-eval", versionset_id],
            trace_id=trace_id,
        )
        obs.flush()
    except Exception:
        # Observability must never fail an evaluation; the control-plane audit
        # trail remains the authoritative evidence path.
        pass

    status = "ok" if answer else "empty"
    _append_provider_log(
        settings,
        {
            "request_id": request_id,
            "status": status,
            "trace_id": trace_id,
            "versionset_id": versionset_id,
            "prompt_digest": prompt_component.get("digest"),
            "kb_manifest_digest": kb_component.get("digest"),
            "model_digest": model_component.get("digest"),
            "answer_digest": "sha256:" + hashlib.sha256(answer.encode("utf-8")).hexdigest(),
        },
    )

    return {
        "request_id": request_id,
        "answer": answer,
        "versionset_id": versionset_id,
        "prompt_digest": prompt_component.get("digest"),
        "kb_manifest_digest": kb_component.get("digest"),
        "model_digest": model_component.get("digest"),
        "retrieval": [],
        "status": status,
        "trace_id": trace_id,
    }
