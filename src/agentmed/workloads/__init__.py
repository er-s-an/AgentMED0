from __future__ import annotations

from typing import Any

from agentmed.kernel import Kernel
from agentmed.workloads.base import WorkloadAdapter, WorkloadSpec
from agentmed.workloads.kotaemon import KotaemonAdapter
from agentmed.workloads.langgraph import LangGraphAdapter

_REGISTRY: dict[str, WorkloadAdapter] = {
    "kotaemon": KotaemonAdapter(),
    "langgraph": LangGraphAdapter(),
}
DEFAULT_SLUG = "kotaemon"


class UnknownWorkload(KeyError):
    pass


def register_adapter(adapter: WorkloadAdapter) -> None:
    _REGISTRY[adapter.spec.slug] = adapter


def unregister_adapter(slug: str) -> None:
    _REGISTRY.pop(slug, None)


def get_adapter(slug: str | None = None) -> WorkloadAdapter:
    key = (slug or DEFAULT_SLUG).strip() or DEFAULT_SLUG
    try:
        return _REGISTRY[key]
    except KeyError as exc:
        raise UnknownWorkload(key) from exc


def list_adapters() -> list[WorkloadSpec]:
    return [adapter.spec for adapter in _REGISTRY.values()]


def adapter_for_case(kernel: Kernel, case: dict[str, Any]) -> WorkloadAdapter:
    app = kernel.store.get("applications", case.get("application_id") or "")
    slug = (app or {}).get("slug") if isinstance(app, dict) else None
    return get_adapter(slug)


_REPO_SLUGS = {
    "github.com/cinnamon/kotaemon": "kotaemon",
    "github.com/langchain-ai/langgraph": "langgraph",
}


def infer_slug_from_url(url: str) -> str | None:
    lowered = (url or "").lower()
    for needle, slug in _REPO_SLUGS.items():
        if needle in lowered:
            return slug
    return None


def resolve_workload_slug(*, url: str | None = None, explicit: str | None = None) -> str:
    if explicit and explicit.strip():
        slug = explicit.strip()
        get_adapter(slug)
        return slug
    inferred = infer_slug_from_url(url or "")
    if inferred:
        get_adapter(inferred)
        return inferred
    if url and "github.com/" in (url or "").lower():
        raise UnknownWorkload("unmapped repository; pass slug")
    return DEFAULT_SLUG
