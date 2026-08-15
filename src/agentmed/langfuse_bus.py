"""Langfuse is the evidence bus. Kernel still owns Case success."""

from __future__ import annotations

from typing import Any

from agentmed.adapters.langfuse import (
    LangfuseUnavailable,
    fetch_langfuse,
    fetch_prompt,
    is_governance_item,
    partition_traces,
    summarize_trace,
)
from agentmed.config import Settings, load_settings
from agentmed.kernel import Kernel
from agentmed.observability import Observability


def prompt_name_for_role(role: str) -> str:
    return f"agentmed-playbook-{role}"


def resolve_prompt(settings: Settings | None, role: str) -> dict[str, Any]:
    """Prefer Langfuse Prompt Management; fall back to the static catalog."""
    settings = settings or load_settings()
    name = prompt_name_for_role(role)
    fetched = fetch_prompt(
        host=settings.langfuse_host,
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        name=name,
        label="production",
    )
    if fetched and fetched.get("prompt"):
        return {
            "name": fetched.get("name") or name,
            "version": fetched.get("version"),
            "prompt": fetched["prompt"],
            "source": "langfuse",
        }
    from agentmed.prompt_catalog import harvest_prompts

    for item in harvest_prompts():
        if item.get("name") == name or (item.get("role") == role and item.get("kind") == "playbook"):
            return {
                "name": item["name"],
                "version": None,
                "prompt": item["prompt"],
                "source": "static",
            }
    return {"name": name, "version": None, "prompt": None, "source": "missing"}


def reproduce_episode(adapter: Any, files: dict[str, str] | None = None) -> dict[str, Any] | None:
    fn = getattr(adapter, "reproduce_episode", None)
    if not callable(fn):
        return None
    try:
        episode = fn(files) if files is not None else fn()
    except TypeError:
        episode = fn()
    return episode if isinstance(episode, dict) else None


def log_target_episode(
    settings: Settings | None,
    *,
    case_id: str,
    episode: dict[str, Any],
) -> dict[str, Any]:
    """Write a real reproduced query to Langfuse. Never invents a passing span."""
    settings = settings or load_settings()
    obs = Observability(settings)
    name = str(episode.get("name") or "target.query")
    meta = {
        "role": "target_app",
        "plane": "target_app",
        "case_id": case_id,
        "product": str((episode.get("metadata") or {}).get("product") or "target"),
        **dict(episode.get("metadata") or {}),
    }
    logged = False
    if obs.enabled:
        obs.generation(
            name=name,
            model="target-harness",
            input_text=episode.get("input"),
            output_text=episode.get("output"),
            metadata=meta,
            tags=["target_app", "eval", str(meta.get("workload") or "workload"), case_id],
        )
        obs.flush()
        logged = True
    return {"logged": logged, "name": name, "case_id": case_id}


def query_case_traces(settings: Settings | None, case_id: str) -> dict[str, Any]:
    settings = settings or load_settings()
    try:
        payload = fetch_langfuse(
            host=settings.langfuse_host,
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            failed_only=False,
            case_id=case_id,
        )
    except LangfuseUnavailable as exc:
        return {
            "ok": False,
            "reason": str(exc),
            "governance": [],
            "target": [],
            "traces": [],
        }
    traces = [item for item in (payload.get("traces") or []) if isinstance(item, dict)]
    parts = partition_traces(traces)
    return {
        "ok": True,
        "reason": None,
        "governance": parts["governance"],
        "target": parts["target"],
        "traces": traces,
    }


def collect_investigation_evidence(
    kernel: Kernel,
    *,
    principal: str,
    case_id: str,
    adapter: Any,
    signal: dict[str, Any],
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Query Langfuse, reproduce the failing query, persist receipts. Do not forge spans."""
    settings = settings or load_settings()
    github = {
        "type": "github_issue",
        "url": signal.get("source_ref"),
        "title": signal.get("title"),
    }
    episode = reproduce_episode(adapter)
    episode_log = None
    if episode:
        episode_log = log_target_episode(settings, case_id=case_id, episode=episode)
    queried = query_case_traces(settings, case_id)
    target = [summarize_trace(item) for item in queried.get("target") or []]
    governance = [summarize_trace(item) for item in queried.get("governance") or []]
    missing: list[str] = []
    if not queried.get("ok"):
        missing.append("langfuse_unreachable" if queried.get("reason") else "langfuse_keys")
        missing.append("target_app_langfuse_traces")
    elif not target:
        missing.append("target_app_langfuse_traces")
    artifacts: list[dict[str, Any]] = [github]
    if episode:
        artifacts.append(
            {
                "type": "target_episode",
                "name": episode.get("name"),
                "leaked": (episode.get("output") or {}).get("leaked"),
                "logged_to_langfuse": bool(episode_log and episode_log.get("logged")),
            }
        )
    artifacts.extend({"type": "langfuse_trace", **item} for item in target)
    github_receipt = kernel.add_evidence(
        principal=principal,
        case_id=case_id,
        kind="github_issue",
        summary=f"Upstream issue {signal.get('source_ref')}: {signal.get('title')}",
        artifacts=[github],
        missing=[],
    )
    langfuse_receipt = kernel.add_evidence(
        principal=principal,
        case_id=case_id,
        kind="langfuse_traces",
        summary=(
            f"Langfuse queried: target={len(target)} governance={len(governance)}"
            + (f"; episode leaked={artifacts[1].get('leaked')}" if episode else "")
        ),
        artifacts=artifacts,
        missing=missing,
    )
    return {
        "queried": bool(queried.get("ok")),
        "needs_context": bool(missing),
        "missing": missing,
        "target_traces": target,
        "governance_traces": governance,
        "episode": episode,
        "episode_logged": bool(episode_log and episode_log.get("logged")),
        "github_evidence": github_receipt,
        "langfuse_evidence": langfuse_receipt,
    }
