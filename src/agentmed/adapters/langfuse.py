from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx


class LangfuseUnavailable(RuntimeError):
    """Langfuse HTTP failed or was not configured. Callers must not invent traces."""


_BUILDER_MARKERS = {"builder", "agent:builder"}
_COT_KEYS = ("input", "output", "prompt", "completion", "generation", "cot", "chain_of_thought")


def _from_timestamp(window: str | None) -> str | None:
    if not window:
        return None
    raw = window.strip()
    if not raw:
        return None
    lowered = raw.lower()
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if lowered[-1] in units and lowered[:-1].isdigit():
        delta = timedelta(seconds=int(lowered[:-1]) * units[lowered[-1]])
        return (datetime.now(timezone.utc) - delta).isoformat()
    return raw


def _roles(item: dict[str, Any]) -> set[str]:
    roles: set[str] = set()
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    role = str(meta.get("role") or item.get("role") or "").strip().lower()
    if role:
        roles.add(role)
    for tag in item.get("tags") or []:
        roles.add(str(tag).strip().lower())
    name = str(item.get("name") or "").lower()
    for marker in ("builder", "verifier", "investigator", "attribution"):
        if marker in name:
            roles.add(marker)
    return roles


def is_builder_item(item: dict[str, Any]) -> bool:
    return bool(_roles(item) & _BUILDER_MARKERS)


def is_agent_cot_item(item: dict[str, Any]) -> bool:
    return bool(_roles(item) & {"builder", "agent:builder", "verifier", "agent:verifier"})


def _strip_cot_fields(item: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(item)
    for key in _COT_KEYS:
        cleaned.pop(key, None)
    observations = []
    found = False
    for key in ("observations", "spans"):
        if key not in item:
            continue
        found = True
        for obs in item.get(key) or []:
            if not isinstance(obs, dict):
                continue
            if is_builder_item(obs):
                continue
            observations.append(_strip_cot_fields(obs))
    if found:
        cleaned["observations"] = observations
        cleaned.pop("spans", None)
    return cleaned


def sanitize_traces(traces: list[dict[str, Any]], principal: str) -> list[dict[str, Any]]:
    """Drop builder generations/CoT when the principal is the verifier. Never forge spans."""
    strip_builder = "verifier" in str(principal).lower()
    out: list[dict[str, Any]] = []
    for item in traces:
        if not isinstance(item, dict):
            continue
        if strip_builder and is_builder_item(item):
            continue
        out.append(_strip_cot_fields(item) if strip_builder else dict(item))
    return out


def fetch_langfuse(
    *,
    host: str,
    public_key: str,
    secret_key: str,
    min_score: float | None = None,
    failed_only: bool = True,
    window: str | None = None,
    case_id: str | None = None,
) -> dict[str, Any]:
    """Server-side Langfuse query. Tests monkeypatch this function; it never prints keys."""
    del min_score, failed_only
    if not host or not public_key or not secret_key:
        raise LangfuseUnavailable("langfuse host or keys missing")
    params: dict[str, Any] = {"limit": 50}
    from_ts = _from_timestamp(window)
    if from_ts:
        params["fromTimestamp"] = from_ts
    base = host.rstrip("/")
    auth = (public_key, secret_key)
    try:
        with httpx.Client(timeout=10.0) as client:
            scores_r = client.get(f"{base}/api/public/scores", params=params, auth=auth)
            traces_r = client.get(f"{base}/api/public/traces", params=params, auth=auth)
            scores_r.raise_for_status()
            traces_r.raise_for_status()
            scores_payload = scores_r.json()
            traces_payload = traces_r.json()
    except Exception as exc:
        raise LangfuseUnavailable(f"{type(exc).__name__}") from exc
    scores = scores_payload.get("data", scores_payload if isinstance(scores_payload, list) else [])
    traces = traces_payload.get("data", traces_payload if isinstance(traces_payload, list) else [])
    if not isinstance(scores, list):
        scores = []
    if not isinstance(traces, list):
        traces = []
    if case_id:
        traces = [item for item in traces if _mentions_case(item, case_id)]
        scores = [item for item in scores if _mentions_case(item, case_id)]
    return {"scores": scores, "traces": traces}


def _mentions_case(item: dict[str, Any], case_id: str) -> bool:
    if not case_id:
        return True
    tags = {str(tag) for tag in (item.get("tags") or [])}
    if case_id in tags:
        return True
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    if str(meta.get("case_id") or "") == case_id:
        return True
    blob = f"{item.get('name') or ''} {item.get('sessionId') or ''} {item.get('id') or ''}"
    return case_id in blob


def summarize_trace(item: dict[str, Any]) -> dict[str, Any]:
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "tags": list(item.get("tags") or []),
        "role": meta.get("role") or item.get("role"),
        "plane": meta.get("plane"),
        "case_id": meta.get("case_id"),
    }


def fetch_prompt(
    *,
    host: str,
    public_key: str,
    secret_key: str,
    name: str,
    label: str = "production",
) -> dict[str, Any] | None:
    """Read one Prompt Management record. None if missing or Langfuse is down."""
    if not host or not public_key or not secret_key or not name:
        return None
    base = host.rstrip("/")
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(
                f"{base}/api/public/v2/prompts/{name}",
                params={"label": label},
                auth=(public_key, secret_key),
            )
        if response.status_code >= 400:
            return None
        payload = response.json()
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    prompt = payload.get("prompt")
    if isinstance(prompt, list):
        prompt = "\n".join(
            str(part.get("content") or part) if isinstance(part, dict) else str(part) for part in prompt
        )
    if not prompt:
        return None
    return {
        "name": payload.get("name") or name,
        "version": payload.get("version"),
        "prompt": prompt,
        "label": label,
    }



def is_governance_item(item: dict[str, Any]) -> bool:
    tags = {str(tag).strip().lower() for tag in (item.get("tags") or [])}
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    if str(meta.get("product") or "").strip().lower() == "agentmed":
        return True
    if str(meta.get("plane") or "").strip().lower() == "governance":
        return True
    name = str(item.get("name") or "").lower()
    if name.startswith("agentmed."):
        return True
    return bool(tags & {"agentmed-governance", "agentmed"})


def partition_traces(traces: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    governance: list[dict[str, Any]] = []
    target: list[dict[str, Any]] = []
    for item in traces:
        if not isinstance(item, dict):
            continue
        if is_governance_item(item):
            governance.append(item)
        else:
            target.append(item)
    return {"governance": governance, "target": target}


def upsert_prompts(
    *,
    host: str,
    public_key: str,
    secret_key: str,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create/update Langfuse Prompt Management records. Never returns secret values."""
    if not host or not public_key or not secret_key:
        return {
            "status": "skipped",
            "reason": "langfuse_keys_missing",
            "upserted": [],
            "failed": [],
        }
    base = host.rstrip("/")
    upserted: list[str] = []
    failed: list[str] = []
    try:
        with httpx.Client(timeout=20.0) as client:
            for record in records:
                name = str(record.get("name") or "").strip()
                prompt = record.get("prompt") or ""
                if not name or not prompt:
                    continue
                body = {
                    "name": name,
                    "type": record.get("type") or "text",
                    "prompt": prompt,
                    "labels": list(record.get("labels") or ["production", "governance"]),
                    "tags": list(record.get("tags") or ["agentmed", "governance"]),
                }
                try:
                    response = client.post(
                        f"{base}/api/public/v2/prompts",
                        json=body,
                        auth=(public_key, secret_key),
                    )
                    if response.status_code >= 400:
                        failed.append(name)
                    else:
                        upserted.append(name)
                except Exception:
                    failed.append(name)
    except Exception as exc:
        return {
            "status": "NEEDS_CONTEXT",
            "reason": type(exc).__name__,
            "upserted": upserted,
            "failed": [item["name"] for item in records if item.get("name")],
        }
    status = "ok" if upserted and not failed else ("NEEDS_CONTEXT" if failed else "skipped")
    return {
        "status": status,
        "upserted": upserted,
        "failed": failed,
        "upserted_count": len(upserted),
        "failed_count": len(failed),
    }


def provision_refs(host: str, *, keys_configured: bool) -> dict[str, Any]:
    base = (host or "").rstrip("/")
    return {
        "host": base,
        "otlp_endpoint_ref": f"{base}/api/public/otel" if base else None,
        "public_key_ref": "env:LANGFUSE_PUBLIC_KEY",
        "secret_key_ref": "env:LANGFUSE_SECRET_KEY",
        "keys_configured": keys_configured,
        "worker_host": "http://host.docker.internal:3001",
        "llm_proxy_ref": "http://host.docker.internal:8088/v1",
        "prompt_management_ref": f"{base}/prompts" if base else None,
    }


def probe_monitor(url: str | None, timeout: float = 5.0) -> dict[str, Any]:
    if not url:
        return {
            "connected": False,
            "missing": ["enterprise_monitor_station"],
            "summary": (
                "No monitor MCP/URL configured; kotaemon #758 demo may skip a real station. "
                "Do not forge metrics."
            ),
        }
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(url)
        if response.status_code >= 500:
            return {
                "connected": False,
                "missing": ["enterprise_monitor_station"],
                "summary": (
                    f"Monitor at reference URL returned {response.status_code}; "
                    "Kernel continues without forged metrics."
                ),
            }
        return {
            "connected": True,
            "missing": ["enterprise_monitor_metrics"],
            "summary": (
                "Monitor reachable; Skill/MCP must query metrics. Kernel stores receipts only. "
                "Do not forge metric values."
            ),
            "status_code": response.status_code,
        }
    except Exception as exc:
        return {
            "connected": False,
            "missing": ["enterprise_monitor_station"],
            "summary": (
                f"Monitor unreachable ({type(exc).__name__}); Kernel continues. "
                "Do not forge metrics."
            ),
        }
