from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from agentmed.adapters.github import fetch_github_issue
from agentmed.config import Settings, load_settings
from agentmed.jsonutil import parse_json_object
from agentmed.kernel import ROLE_PRINCIPALS, Kernel
from agentmed.live import LiveStackError, assert_live
from agentmed.llm import LLM
from agentmed.observability import Observability
from agentmed.prompts import (
    BUILDER_SYSTEM,
    CURATOR_SYSTEM,
    INTAKE_SYSTEM,
    INVESTIGATOR_SYSTEM,
    LEAD_SYSTEM,
    VERIFIER_SYSTEM,
    builder_user_prompt,
)
from agentmed.release import verify_candidate, write_shadow_and_rollback
from agentmed.store import Store

FALLBACK_EXPECTED = (
    "When the user selects only file A, answers/retrieval must not include content from file B."
)
FALLBACK_BADCASE = "upload a.pdf and b.pdf; select only a.pdf; ask a question"
FALLBACK_JUDGE = (
    "retrieved/generated text for the selected file must not contain the other file's unique content"
)
GATE_STYLE_INSTRUCTION = """Gate requirement for lightrag_store.py:
- insert(text, file_id=...) MUST persist file_id on each chunk (do not drop or del file_id).
- query(text, file_ids=...) MUST return only chunks whose file_id is in the selected file_ids.
- query with empty or None file_ids MUST return [].
Return JSON with keys: summary, risk, lightrag_store_py, diff.
lightrag_store_py must be the full file contents after your fix.
"""
KOTAEMON_REPO = "https://github.com/Cinnamon/kotaemon"
KOTAEMON_COMMIT = "ffe766f24d4ef8a91f8c61871d2b5a1930aa204e"
WORKLOAD = "workloads/kotaemon-lightrag-scope"


def _llm_enabled(settings: Settings) -> bool:
    return settings.llm_enabled


def _complete(llm: LLM | None, enabled: bool, *, require_live: bool, **kwargs: Any) -> str | None:
    if not enabled or llm is None:
        if require_live:
            raise LiveStackError("Step Plan LLM is required for a live run")
        return None
    try:
        return llm.complete(**kwargs)
    except Exception as exc:
        message = f"llm.{kwargs.get('role', '?')} failed: {type(exc).__name__}: {exc}"
        print(message, file=sys.stderr)
        if require_live:
            raise LiveStackError(message) from exc
        return None


def _stores_and_filters_file_id(source: str) -> bool:
    if not source or "class LightRAGStore" not in source:
        return False
    if "del file_id" in source:
        return False
    stores = '"file_id": file_id' in source or "'file_id': file_id" in source
    filters = (
        'chunk.get("file_id")' in source
        or "chunk.get('file_id')" in source
        or "in selected" in source
    )
    return stores and filters


def _unified_diff(old: str, new: str, path: str = "lightrag_store.py") -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


def _write_export(bundle: dict[str, Any], data_dir: Path, case_id: str) -> Path:
    export_dir = data_dir / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    path = export_dir / f"{case_id}.json"
    path.write_text(json.dumps(bundle, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path


def _parse_intake(text: str | None, issue: dict[str, Any]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    if text:
        try:
            parsed = parse_json_object(text)
        except ValueError:
            parsed = {}
    title = str(parsed.get("title") or issue.get("title") or "kotaemon file scope")
    summary = str(parsed.get("summary") or issue.get("body") or title)
    expected = str(parsed.get("expected_behavior") or FALLBACK_EXPECTED)
    badcase = str(parsed.get("badcase_input") or FALLBACK_BADCASE)
    judge = str(parsed.get("judge") or FALLBACK_JUDGE)
    ai_related = parsed.get("ai_related", True)
    return {
        "title": title,
        "summary": summary,
        "expected_behavior": expected,
        "badcase_input": badcase,
        "judge": judge,
        "ai_related": ai_related,
    }


def _parse_builder(text: str | None) -> dict[str, Any] | None:
    if not text:
        return None
    try:
        payload = parse_json_object(text)
    except ValueError:
        return None
    source = payload.get("lightrag_store_py")
    if not isinstance(source, str) or not source.strip():
        return None
    if not _stores_and_filters_file_id(source):
        return None
    return payload


def _candidate_fields(payload: dict[str, Any] | None, *, fallback: bool) -> tuple[str, str, str, str]:
    if fallback or not payload or not isinstance(payload.get("lightrag_store_py"), str):
        raise LiveStackError(
            "Builder did not return a gate-legal candidate; golden fallback is disabled"
        )
    source = payload["lightrag_store_py"]
    summary = str(payload.get("summary") or "store file_id on insert and filter query by selected file_ids")
    risk = str(payload.get("risk") or "low: scoped retrieval change confined to LightRAGStore")
    diff = str(payload.get("diff") or "")
    if diff in {"", "see files"}:
        diff = _unified_diff("", source) or "see files"
    return source, summary, diff, risk


def run_mvp(*, signal_url: str, accept: bool = True, data_dir: Path | None = None) -> dict:
    load_dotenv()
    settings = load_settings()
    live_report = None
    if settings.require_live:
        live_report = assert_live(settings, signal_url=signal_url)
    root = Path(data_dir) if data_dir is not None else Path(settings.agentmed_data_dir)
    root.mkdir(parents=True, exist_ok=True)
    store = Store(settings.database_url, settings.agentmed_data_dir)
    kernel = Kernel(store)
    obs = Observability(settings)
    llm_on = _llm_enabled(settings)
    if settings.require_live and not llm_on:
        raise LiveStackError("STEP_API_KEY is required for a live run")
    llm = LLM(settings, obs) if llm_on else None

    with obs.trace_role("intake", "pending", "intake.parse"):
        issue = fetch_github_issue(signal_url, settings.github_token)
        intake_user = (
            f"GitHub issue URL: {issue.get('url', signal_url)}\n"
            f"Title: {issue.get('title')}\n\n{issue.get('body')}\n\n"
            "Return JSON with keys: title, summary, expected_behavior, badcase_input, judge, ai_related."
        )
        intake_text = _complete(
            llm,
            llm_on,
            require_live=settings.require_live,
            role="intake",
            system=INTAKE_SYSTEM,
            user=intake_user,
        )
        intake = _parse_intake(intake_text, issue)
        app = kernel.ensure_app(slug="kotaemon", name="kotaemon", repo=KOTAEMON_REPO)
        signal = kernel.ingest_signal(
            principal=ROLE_PRINCIPALS["intake"],
            source_type="github_issue",
            source_ref=issue.get("url") or signal_url,
            title=intake["title"],
            body=str(issue.get("body") or intake["summary"]),
            application_id=app["id"],
            raw=issue,
        )
        case = kernel.open_case(
            principal=ROLE_PRINCIPALS["intake"],
            signal=signal,
            application=app,
        )

    case_id = case["id"]
    lead_summary = ""
    builder_fallback = False

    def finish(extra: dict[str, Any] | None = None) -> dict[str, Any]:
        bundle = kernel.export_case(case_id)
        if extra:
            bundle.update(extra)
        bundle["lead_summary"] = lead_summary
        bundle["langfuse_enabled"] = obs.enabled
        bundle["llm_enabled"] = llm_on
        bundle["builder_fallback"] = builder_fallback
        bundle["live"] = live_report
        bundle["require_live"] = settings.require_live
        export_path = _write_export(bundle, root, case_id)
        bundle["export_path"] = str(export_path)
        obs.flush()
        return bundle

    if not accept:
        return finish()

    spec = kernel.confirm_acceptance(
        principal="human:cli",
        case_id=case_id,
        expected_behavior=intake["expected_behavior"],
        badcase_input=intake["badcase_input"],
        judge=intake["judge"],
    )

    with obs.trace_role("investigator", case_id, "investigator.collect"):
        kernel.bind_version_snapshot(
            principal=ROLE_PRINCIPALS["investigator"],
            case_id=case_id,
            manifest={
                "repository": KOTAEMON_REPO,
                "commit": KOTAEMON_COMMIT,
                "issue": issue.get("url") or signal_url,
                "workload": WORKLOAD,
            },
        )
        kernel.add_evidence(
            principal=ROLE_PRINCIPALS["investigator"],
            case_id=case_id,
            kind="github_issue",
            summary=f"Upstream issue {issue.get('url') or signal_url}: {issue.get('title')}",
            artifacts=[
                {
                    "type": "github_issue",
                    "url": issue.get("url") or signal_url,
                    "title": issue.get("title"),
                    "number": issue.get("number"),
                }
            ],
            missing=["target_app_langfuse_traces"],
        )
        _complete(
            llm,
            llm_on,
            require_live=settings.require_live,
            role="investigator",
            system=INVESTIGATOR_SYSTEM,
            user=(
                f"Issue: {issue.get('title')}\n{issue.get('body')}\n"
                f"Snapshot: {KOTAEMON_REPO}@{KOTAEMON_COMMIT}\n"
                "Missing live Langfuse target traces. Summarize evidence only. Do not patch."
            ),
        )

    with obs.trace_role("attribution", case_id, "attribution.skip"):
        kernel.add_investigation(
            principal=ROLE_PRINCIPALS["attribution"],
            case_id=case_id,
            hypothesis=(
                "file_id is not passed through LightRAG insert/query, so selecting file A still "
                "retrieves content indexed from file B"
            ),
            conclusion="SUPPORTED",
            uncertainty=(
                "skipped heavy factorial experiment; issue author already pointed to insert/query call sites"
            ),
        )

    def submit_from_llm(user: str, *, allow_retry: bool) -> dict[str, Any]:
        nonlocal builder_fallback
        payload = _parse_builder(
            _complete(
                llm,
                llm_on,
                require_live=settings.require_live,
                role="builder",
                system=BUILDER_SYSTEM,
                user=user,
            )
        )
        fallback = payload is None
        if fallback and allow_retry and llm_on:
            payload = _parse_builder(
                _complete(
                    llm,
                    llm_on,
                    require_live=settings.require_live,
                    role="builder",
                    system=BUILDER_SYSTEM,
                    user=f"{user}\n\n{GATE_STYLE_INSTRUCTION}",
                )
            )
            fallback = payload is None
        builder_fallback = fallback
        source, summary, diff, risk = _candidate_fields(payload, fallback=fallback)
        return kernel.submit_candidate(
            principal=ROLE_PRINCIPALS["builder"],
            case_id=case_id,
            summary=summary,
            diff=diff,
            files={"lightrag_store.py": source},
            risk=risk,
        )

    with obs.trace_role("builder", case_id, "builder.propose"):
        candidate = submit_from_llm(builder_user_prompt(issue, spec), allow_retry=True)

    with obs.trace_role("verifier", case_id, "verifier.verify"):
        report = verify_candidate(kernel, case_id, candidate)
        _complete(
            llm,
            llm_on,
            require_live=settings.require_live,
            role="verifier",
            system=VERIFIER_SYSTEM,
            user=json.dumps({"gate_evidence": report.get("evidence")}, default=str),
        )

    if report.get("verdict") == "REJECTED":
        gate_only_user = (
            "Propose a new candidate from GateReport evidence only. "
            "Do not rely on prior builder reasoning.\n"
            f"{json.dumps(report.get('evidence'), default=str)}\n\n"
            f"{GATE_STYLE_INSTRUCTION}"
        )
        with obs.trace_role("builder", case_id, "builder.retry"):
            candidate = submit_from_llm(gate_only_user, allow_retry=False)
        with obs.trace_role("verifier", case_id, "verifier.reverify"):
            report = verify_candidate(kernel, case_id, candidate)
            _complete(
                llm,
                llm_on,
                require_live=settings.require_live,
                role="verifier",
                system=VERIFIER_SYSTEM,
                user=json.dumps({"gate_evidence": report.get("evidence")}, default=str),
            )

    if report.get("verdict") == "VERIFIED":
        runtime = Path(settings.agentmed_data_dir) / "runtime" / case_id
        write_shadow_and_rollback(kernel, case_id, candidate, runtime)

    with obs.trace_role("curator", case_id, "curator.close"):
        curator_notes = _complete(
            llm,
            llm_on,
            require_live=settings.require_live,
            role="curator",
            system=CURATOR_SYSTEM,
            user=(
                f"Case {case_id} gate verdict={report.get('verdict')}. "
                "Write a short regression-asset summary about scoping file_id on insert/query."
            ),
        )
        kernel.close_with_asset(
            principal=ROLE_PRINCIPALS["curator"],
            case_id=case_id,
            summary=curator_notes
            or "Regression asset: LightRAG must persist file_id on insert and filter query by selection.",
            probes=["eval/test_file_scope.py", "eval/test_empty_selection.py"],
            lessons=(
                "Always pass and persist file_id at insert; query must filter chunks by selected "
                "file_ids; empty selection must return no chunks."
            ),
        )

    with obs.trace_role("lead", case_id, "lead.summarize"):
        lead_summary = (
            _complete(
                llm,
                llm_on,
                require_live=settings.require_live,
                role="lead",
                system=LEAD_SYSTEM,
                user=f"Summarize closed case {case_id} with gate verdict {report.get('verdict')}. Do not change state.",
            )
            or f"Case {case_id} finished with gate verdict {report.get('verdict')}."
        )

    return finish()
