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
    if case_id:
        params["filter"] = case_id
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
    return {"scores": scores, "traces": traces}



def provision_refs(host: str, *, keys_configured: bool) -> dict[str, Any]:
    base = (host or "").rstrip("/")
    return {
        "host": base,
        "otlp_endpoint_ref": f"{base}/api/public/otel" if base else None,
        "public_key_ref": "env:LANGFUSE_PUBLIC_KEY",
        "secret_key_ref": "env:LANGFUSE_SECRET_KEY",
        "keys_configured": keys_configured,
        "worker_host": "http://host.docker.internal:3001",
    }


def probe_monitor(url: str | None, timeout: float = 5.0) -> dict[str, Any]:
    if not url:
        return {
            "connected": False,
            "missing": ["enterprise_monitor"],
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
                "missing": ["enterprise_monitor_unreachable"],
                "summary": (
                    f"Monitor at reference URL returned {response.status_code}; "
                    "Kernel continues without forged metrics."
                ),
            }
        return {
            "connected": True,
            "missing": [],
            "summary": "Monitor reachable; attach artifacts only, never raw secrets.",
            "status_code": response.status_code,
        }
    except Exception as exc:
        return {
            "connected": False,
            "missing": ["enterprise_monitor_unreachable"],
            "summary": (
                f"Monitor unreachable ({type(exc).__name__}); Kernel continues. "
                "Do not forge metrics."
            ),
        }
