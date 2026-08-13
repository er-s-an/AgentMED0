from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def _ci_safe_env() -> None:
    """CI and local pytest never require AgentTeams / Langfuse / Step Plan."""
    os.environ.setdefault("REQUIRE_LIVE", "false")
    os.environ.setdefault("LANGFUSE_PUBLIC_KEY", "")
    os.environ.setdefault("LANGFUSE_SECRET_KEY", "")
