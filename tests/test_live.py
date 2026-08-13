from __future__ import annotations

from agentmed.config import Settings
from agentmed.live import Probe, as_report, assert_live, LiveStackError
from agentmed.team.playbook import _candidate_fields


def test_as_report_ok_requires_every_probe() -> None:
    probes = [
        Probe("agentteams", True, "up", "docker"),
        Probe("langfuse", True, "ok", "http"),
        Probe("model", False, "missing key", "step"),
        Probe("gate", True, "base fails", "pytest"),
        Probe("github", True, "issue 758", "api"),
    ]
    report = as_report(probes)
    assert report["ok"] is False
    assert report["probes"][2]["name"] == "model"


def test_assert_live_raises_with_failed_names(monkeypatch) -> None:
    def fake_probe_all(settings, *, signal_url=""):
        return [
            Probe("agentteams", False, "no containers", "docker"),
            Probe("langfuse", True, "ok", "http"),
            Probe("model", True, "ok", "step"),
            Probe("gate", True, "ok", "pytest"),
            Probe("github", True, "ok", "api"),
        ]

    monkeypatch.setattr("agentmed.live.probe_all", fake_probe_all)
    try:
        assert_live(Settings(require_live=True))
        raise AssertionError("expected LiveStackError")
    except LiveStackError as exc:
        assert "agentteams" in str(exc)


def test_builder_golden_fallback_is_disabled() -> None:
    try:
        _candidate_fields(None, fallback=True)
        raise AssertionError("expected LiveStackError")
    except LiveStackError as exc:
        assert "golden fallback is disabled" in str(exc)
