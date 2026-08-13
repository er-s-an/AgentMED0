from __future__ import annotations

import os
import sys
from typing import Any

from agentmed.config import Settings
from agentmed.live import LiveStackError


class Observability:
    """Langfuse is the review/diagnosis plane. Kernel remains source of truth."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.enabled = settings.langfuse_enabled
        self.client = None
        if not self.enabled:
            if settings.require_live:
                raise LiveStackError("Langfuse keys missing; live run requires LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY")
            return
        os.environ["LANGFUSE_HOST"] = settings.langfuse_host
        os.environ["LANGFUSE_PUBLIC_KEY"] = settings.langfuse_public_key
        os.environ["LANGFUSE_SECRET_KEY"] = settings.langfuse_secret_key
        os.environ["LANGFUSE_BASE_URL"] = settings.langfuse_host
        try:
            from langfuse import get_client

            self.client = get_client()
        except Exception as exc:
            if settings.require_live:
                raise LiveStackError(f"Langfuse client failed to start: {type(exc).__name__}: {exc}") from exc
            print(f"langfuse client failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            self.enabled = False
            self.client = None

    def trace_role(self, role: str, case_id: str, name: str):
        if not self.enabled or self.client is None:
            if self.settings.require_live:
                raise LiveStackError(f"Langfuse span {name} unavailable")
            return _NullTrace()
        try:
            ctx = self.client.start_as_current_observation(
                as_type="span",
                name=name,
                metadata={"role": role, "case_id": case_id, "product": "agentmed"},
            )
            if hasattr(ctx, "__enter__"):
                return ctx
        except Exception as exc:
            if self.settings.require_live:
                raise LiveStackError(f"Langfuse span {name} failed: {type(exc).__name__}: {exc}") from exc
            return _NullTrace()
        return _NullTrace()

    def generation(
        self,
        name: str,
        model: str,
        input_text: str,
        output_text: str,
        usage: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled or self.client is None:
            return
        try:
            observation = self.client.start_observation(as_type="generation", name=name, model=model, input=input_text)
            observation.update(output=output_text, usage_details=usage or {})
            observation.end()
        except Exception as exc:
            if self.settings.require_live:
                raise LiveStackError(f"Langfuse generation {name} failed: {type(exc).__name__}: {exc}") from exc

    def event(self, name: str, metadata: dict[str, Any]) -> None:
        if not self.enabled or self.client is None:
            return
        try:
            self.client.create_event(name=name, metadata=metadata)
        except Exception as exc:
            if self.settings.require_live:
                raise LiveStackError(f"Langfuse event {name} failed: {type(exc).__name__}: {exc}") from exc

    def flush(self) -> None:
        if self.client is not None:
            try:
                self.client.flush()
            except Exception as exc:
                if self.settings.require_live:
                    raise LiveStackError(f"Langfuse flush failed: {type(exc).__name__}: {exc}") from exc


class _NullTrace:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def update(self, **kwargs):
        return None
