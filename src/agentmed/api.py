from __future__ import annotations

from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from agentmed.adapters.github import fetch_github_issue
from agentmed.config import load_settings
from agentmed.gate import base_source
from agentmed.kernel import ROLE_PRINCIPALS, Kernel, KernelError
from agentmed.release import verify_candidate, write_shadow_and_rollback
from agentmed.store import Store
from agentmed.workload import (
    ATTRIBUTE_HYPOTHESIS,
    DEFAULT_BADCASE,
    DEFAULT_EXPECTED,
    DEFAULT_JUDGE,
    KOTAEMON_COMMIT,
    KOTAEMON_REPO,
    KOTAEMON_SNAPSHOT,
    WORKLOAD,
)

load_dotenv()

app = FastAPI(title="AgentMED Kernel")


def _kernel() -> Kernel:
    settings = load_settings()
    store = Store(settings.database_url, Path(settings.agentmed_data_dir))
    return Kernel(store)


def _require(principal: str | None, allowed: set[str]) -> str:
    if not principal:
        raise HTTPException(status_code=401, detail="X-AgentMED-Principal required")
    if principal not in allowed and not (principal.startswith("human:") and "human:*" in allowed):
        raise HTTPException(status_code=403, detail=f"principal {principal} not allowed")
    return principal


@app.get("/ready")
def ready() -> dict:
    return {"kernel": "ok"}


@app.get("/health")
def health() -> dict:
    return {"kernel": "ok"}


class IngestBody(BaseModel):
    url: str
    title: str | None = None
    summary: str | None = None
    expected_behavior: str | None = None
    badcase_input: str | None = None
    judge: str | None = None


class AcceptBody(BaseModel):
    expected_behavior: str = DEFAULT_EXPECTED
    badcase_input: str = DEFAULT_BADCASE
    judge: str = DEFAULT_JUDGE


class AttributeBody(BaseModel):
    hypothesis: str = ATTRIBUTE_HYPOTHESIS
    conclusion: str = "SUPPORTED"
    uncertainty: str = (
        "skipped heavy factorial experiment; issue author already pointed to insert/query call sites"
    )


class CandidateBody(BaseModel):
    summary: str
    diff: str = ""
    lightrag_store_py: str
    risk: str = "low"


class CloseBody(BaseModel):
    summary: str
    probes: list[str] = Field(
        default_factory=lambda: ["eval/test_file_scope.py", "eval/test_empty_selection.py"]
    )
    lessons: str = (
        "Always pass and persist file_id at insert; query must filter chunks by selected "
        "file_ids; empty selection must return no chunks."
    )


@app.post("/v1/signals/ingest")
def ingest_signal(
    body: IngestBody,
    x_agentmed_principal: str | None = Header(default=None, alias="X-AgentMED-Principal"),
) -> dict[str, Any]:
    principal = _require(x_agentmed_principal, {ROLE_PRINCIPALS["intake"], ROLE_PRINCIPALS["lead"]})
    settings = load_settings()
    try:
        issue = fetch_github_issue(body.url, settings.github_token)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"github ingest failed: {exc}") from exc
    kernel = _kernel()
    app_row = kernel.ensure_app(slug="kotaemon", name="kotaemon", repo=KOTAEMON_REPO)
    title = body.title or issue.get("title") or "kotaemon file scope"
    signal = kernel.ingest_signal(
        principal=principal,
        source_type="github_issue",
        source_ref=issue.get("url") or body.url,
        title=title,
        body=str(issue.get("body") or body.summary or title),
        application_id=app_row["id"],
        raw=issue,
    )
    case = kernel.open_case(principal=principal, signal=signal, application=app_row)
    return {
        "signal": signal,
        "case": case,
        "issue": {"url": issue.get("url"), "title": issue.get("title"), "number": issue.get("number")},
        "draft_spec": {
            "expected_behavior": body.expected_behavior or DEFAULT_EXPECTED,
            "badcase_input": body.badcase_input or DEFAULT_BADCASE,
            "judge": body.judge or DEFAULT_JUDGE,
        },
    }


@app.post("/v1/cases/{case_id}/accept")
def accept_case(
    case_id: str,
    body: AcceptBody,
    x_agentmed_principal: str | None = Header(default=None, alias="X-AgentMED-Principal"),
) -> dict[str, Any]:
    principal = _require(x_agentmed_principal, {"human:*"})
    try:
        spec = _kernel().confirm_acceptance(
            principal=principal,
            case_id=case_id,
            expected_behavior=body.expected_behavior,
            badcase_input=body.badcase_input,
            judge=body.judge,
        )
    except KernelError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return spec


@app.post("/v1/cases/{case_id}/investigate")
def investigate(
    case_id: str,
    x_agentmed_principal: str | None = Header(default=None, alias="X-AgentMED-Principal"),
) -> dict[str, Any]:
    principal = _require(x_agentmed_principal, {ROLE_PRINCIPALS["investigator"]})
    kernel = _kernel()
    try:
        case = kernel._case(case_id)
        if case.get("version_snapshot_id"):
            snapshot = kernel.store.get("version_snapshots", case["version_snapshot_id"])
            return {
                "snapshot": snapshot,
                "evidence": None,
                "reused": True,
                "workload": WORKLOAD,
                "commit": KOTAEMON_COMMIT,
            }
        signal = kernel.store.get("signals", case["signal_id"]) or {}
        snapshot = kernel.bind_version_snapshot(
            principal=principal,
            case_id=case_id,
            manifest={**KOTAEMON_SNAPSHOT, "issue": signal.get("source_ref")},
        )
        evidence = kernel.add_evidence(
            principal=principal,
            case_id=case_id,
            kind="github_issue",
            summary=f"Upstream issue {signal.get('source_ref')}: {signal.get('title')}",
            artifacts=[{"type": "github_issue", "url": signal.get("source_ref"), "title": signal.get("title")}],
            missing=["target_app_langfuse_traces"],
        )
    except KernelError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"snapshot": snapshot, "evidence": evidence, "workload": WORKLOAD, "commit": KOTAEMON_COMMIT}


@app.post("/v1/cases/{case_id}/attribute")
def attribute(
    case_id: str,
    body: AttributeBody,
    x_agentmed_principal: str | None = Header(default=None, alias="X-AgentMED-Principal"),
) -> dict[str, Any]:
    principal = _require(x_agentmed_principal, {ROLE_PRINCIPALS["attribution"]})
    try:
        return _kernel().add_investigation(
            principal=principal,
            case_id=case_id,
            hypothesis=body.hypothesis,
            conclusion=body.conclusion,
            uncertainty=body.uncertainty,
        )
    except KernelError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/v1/cases/{case_id}/builder-context")
def builder_context(
    case_id: str,
    x_agentmed_principal: str | None = Header(default=None, alias="X-AgentMED-Principal"),
) -> dict[str, Any]:
    _require(x_agentmed_principal, {ROLE_PRINCIPALS["builder"], ROLE_PRINCIPALS["lead"]})
    kernel = _kernel()
    try:
        bundle = kernel.export_case(case_id)
    except KernelError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "case_id": case_id,
        "acceptance_spec": bundle.get("acceptance_spec"),
        "version_snapshot": bundle.get("version_snapshot"),
        "signal": {
            "title": (bundle.get("signal") or {}).get("title"),
            "body": (bundle.get("signal") or {}).get("body"),
            "source_ref": (bundle.get("signal") or {}).get("source_ref"),
        },
        "lightrag_store_py": base_source(),
        "instruction": (
            "Return a full replacement for lightrag_store.py. insert must persist file_id; "
            "query(file_ids=...) must return only matching chunks; empty file_ids must return []. "
            "Do not include eval/ tests. POST the file to /v1/cases/{id}/candidates."
        ),
    }


@app.post("/v1/cases/{case_id}/candidates")
def submit_candidate(
    case_id: str,
    body: CandidateBody,
    x_agentmed_principal: str | None = Header(default=None, alias="X-AgentMED-Principal"),
) -> dict[str, Any]:
    principal = _require(x_agentmed_principal, {ROLE_PRINCIPALS["builder"]})
    try:
        return _kernel().submit_candidate(
            principal=principal,
            case_id=case_id,
            summary=body.summary,
            diff=body.diff,
            files={"lightrag_store.py": body.lightrag_store_py},
            risk=body.risk,
        )
    except KernelError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/v1/cases/{case_id}/verifier-context")
def verifier_context(
    case_id: str,
    x_agentmed_principal: str | None = Header(default=None, alias="X-AgentMED-Principal"),
) -> dict[str, Any]:
    _require(x_agentmed_principal, {ROLE_PRINCIPALS["verifier"]})
    kernel = _kernel()
    try:
        bundle = kernel.export_case(case_id)
    except KernelError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    candidate = (bundle.get("candidates") or [{}])[-1] if bundle.get("candidates") else {}
    files = dict(candidate.get("files") or {})
    return {
        "case_id": case_id,
        "candidate_id": candidate.get("id"),
        "candidate_digest": candidate.get("digest"),
        "files": files,
        "acceptance_spec": bundle.get("acceptance_spec"),
        "note": "Builder chain-of-thought is withheld. POST /v1/cases/{id}/verify to run Gate.",
    }


@app.post("/v1/cases/{case_id}/verify")
def verify(
    case_id: str,
    x_agentmed_principal: str | None = Header(default=None, alias="X-AgentMED-Principal"),
) -> dict[str, Any]:
    principal = _require(x_agentmed_principal, {ROLE_PRINCIPALS["verifier"]})
    kernel = _kernel()
    try:
        case = kernel._case(case_id)
        candidate_id = case.get("candidate_id")
        if not candidate_id:
            raise KernelError("no candidate to verify")
        candidate = kernel.store.get("candidates", candidate_id)
        if not candidate:
            raise KernelError("candidate missing")
        return verify_candidate(kernel, case_id, candidate)
    except KernelError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/cases/{case_id}/release")
def release(
    case_id: str,
    x_agentmed_principal: str | None = Header(default=None, alias="X-AgentMED-Principal"),
) -> dict[str, Any]:
    principal = _require(
        x_agentmed_principal,
        {ROLE_PRINCIPALS["controller"], ROLE_PRINCIPALS["lead"]},
    )
    del principal
    settings = load_settings()
    kernel = _kernel()
    try:
        case = kernel._case(case_id)
        candidate_id = case.get("candidate_id")
        if not candidate_id:
            raise KernelError("no candidate")
        candidate = kernel.store.get("candidates", candidate_id)
        runtime = Path(settings.agentmed_data_dir) / "runtime" / case_id
        return write_shadow_and_rollback(kernel, case_id, candidate, runtime)
    except KernelError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/cases/{case_id}/close")
def close_case(
    case_id: str,
    body: CloseBody,
    x_agentmed_principal: str | None = Header(default=None, alias="X-AgentMED-Principal"),
) -> dict[str, Any]:
    principal = _require(x_agentmed_principal, {ROLE_PRINCIPALS["curator"]})
    try:
        return _kernel().close_with_asset(
            principal=principal,
            case_id=case_id,
            summary=body.summary,
            probes=body.probes,
            lessons=body.lessons,
        )
    except KernelError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/v1/cases")
def list_cases(source_ref: str | None = None) -> dict[str, Any]:
    kernel = _kernel()
    if source_ref:
        case = kernel.find_case_by_source_ref(source_ref)
        return {"cases": [case] if case else []}
    return {"cases": kernel.list_cases()}


@app.get("/v1/cases/{case_id}")
def get_case(case_id: str) -> dict:
    try:
        bundle = _kernel().export_case(case_id)
    except KernelError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return bundle.get("case") or bundle


@app.get("/v1/cases/{case_id}/evidence")
def get_evidence(case_id: str) -> dict:
    try:
        return _kernel().export_case(case_id)
    except KernelError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
