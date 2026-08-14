from __future__ import annotations

import os

import pytest


KOTAEMON_ACCEPT = {
    "expected_behavior": "selected file A must not retrieve file B",
    "badcase_input": "upload a.pdf and b.pdf; select only a.pdf",
    "judge": "eval",
}


@pytest.fixture(scope="session", autouse=True)
def _ci_safe_env() -> None:
    """CI and local pytest never require AgentTeams / Langfuse / Step Plan."""
    os.environ.setdefault("REQUIRE_LIVE", "false")
    os.environ.setdefault("LANGFUSE_PUBLIC_KEY", "")
    os.environ.setdefault("LANGFUSE_SECRET_KEY", "")
