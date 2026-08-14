from __future__ import annotations

from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import Body, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from agentmed.adapters import langfuse as langfuse_adapter
from agentmed.adapters.github import fetch_github_issue
from agentmed.adapters.langfuse import (
    LangfuseUnavailable,
    partition_traces,
    probe_monitor,
    provision_refs,
    sanitize_traces,
    upsert_prompts,
)
from agentmed.llm_proxy import models_payload, proxy_chat
from agentmed.prompt_catalog import catalog_summary, harvest_prompts
from agentmed.config import load_settings
from agentmed.gate import base_source
from agentmed.kernel import ROLE_PRINCIPALS, Kernel, KernelError
from agentmed.release import verify_candidate, write_draft_patch, write_shadow_and_rollback
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

_BUILDER_ROLES = {"builder", "agent:builder"}
_COT_ROLES = {"builder", "agent:builder", "verifier", "agent:verifier"}
_TRACE_ROLES = {"investigator", "attribution", "verifier", "lead"}
_PRINCIPAL_TO_TRACE_ROLE = {
    ROLE_PRINCIPALS["investigator"]: "investigator",
    ROLE_PRINCIPALS["attribution"]: "attribution",
    ROLE_PRINCIPALS["verifier"]: "verifier",
    ROLE_PRINCIPALS["lead"]: "lead",
}
_GOVERNANCE_READERS = {
    ROLE_PRINCIPALS["intake"],
    ROLE_PRINCIPALS["lead"],
    ROLE_PRINCIPALS["investigator"],
    ROLE_PRINCIPALS["attribution"],
    ROLE_PRINCIPALS["curator"],
    ROLE_PRINCIPALS["controller"],
    ROLE_PRINCIPALS["verifier"],
    "human:*",
}


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


def _langfuse_needs_context(missing: str = "langfuse_traces") -> dict[str, Any]:
    return {
        "status": "NEEDS_CONTEXT",
        "needs_context": True,
        "reason": missing,
        "missing": [missing],
        "signal": None,
        "case": None,
        "signals": [],
        "cases": [],
    }


def _item_roles(item: dict[str, Any]) -> set[str]:
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


def _is_builder_item(item: dict[str, Any]) -> bool:
    roles = _item_roles(item)
    return bool(roles & _BUILDER_ROLES) or "builder" in {str(x).lower() for x in (item.get("tags") or [])}


def _is_agent_cot_item(item: dict[str, Any]) -> bool:
    return bool(_item_roles(item) & _COT_ROLES)


def _score_failed(score: dict[str, Any], min_score: float | None) -> bool:
    value = score.get("value")
    if value is None:
        text = str(score.get("stringValue") or score.get("comment") or "").lower()
        return any(token in text for token in ("fail", "failed", "error"))
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return False
    threshold = 1.0 if min_score is None else min_score
    return numeric < threshold


def _sanitize_trace(item: dict[str, Any], *, strip_builder: bool) -> dict[str, Any] | None:
    if strip_builder and _is_builder_item(item):
        return None
    cleaned = dict(item)
    if strip_builder:
        for key in ("input", "output", "prompt", "completion", "generation", "cot", "chain_of_thought"):
            cleaned.pop(key, None)
        observations = []
        for obs in item.get("observations") or item.get("spans") or []:
            if not isinstance(obs, dict):
                continue
            if _is_builder_item(obs):
                continue
            obs_clean = dict(obs)
            for key in ("input", "output", "prompt", "completion", "generation", "cot", "chain_of_thought"):
                obs_clean.pop(key, None)
            observations.append(obs_clean)
        if "observations" in item or "spans" in item:
            cleaned["observations"] = observations
            cleaned.pop("spans", None)
    return cleaned


def low_score_events(
    settings,
    min_score: float = 0.5,
    limit: int = 50,
    window: str | None = None,
    failed_only: bool = True,
    case_id: str | None = None,
) -> list[dict[str, Any]]:
    payload = langfuse_adapter.fetch_langfuse(
        host=settings.langfuse_host,
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        min_score=min_score,
        failed_only=failed_only,
        window=window,
        case_id=case_id,
    )
    scores = [item for item in (payload.get("scores") or []) if isinstance(item, dict)]
    scores = [item for item in scores if not langfuse_adapter.is_agent_cot_item(item)]
    if failed_only:
        scores = [item for item in scores if _score_failed(item, min_score)]
    return scores[:limit]


def _query_langfuse(
    *,
    min_score: float | None = None,
    failed_only: bool = True,
    window: str | None = None,
    case_id: str | None = None,
) -> dict[str, Any]:
    settings = load_settings()
    return langfuse_adapter.fetch_langfuse(
        host=settings.langfuse_host,
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        min_score=min_score,
        failed_only=failed_only,
        window=window,
        case_id=case_id,
    )


def _pick_langfuse_eval(
    payload: dict[str, Any],
    *,
    min_score: float | None,
    failed_only: bool,
) -> dict[str, Any] | None:
    scores = [item for item in (payload.get("scores") or []) if isinstance(item, dict)]
    traces = [item for item in (payload.get("traces") or []) if isinstance(item, dict)]
    usable_scores = [item for item in scores if not _is_agent_cot_item(item)]
    if failed_only:
        usable_scores = [item for item in usable_scores if _score_failed(item, min_score)]
    if usable_scores:
        score = usable_scores[0]
        source_ref = str(score.get("id") or score.get("traceId") or "").strip()
        if not source_ref:
            return None
        if score.get("id"):
            source_ref = f"langfuse:score:{score['id']}"
        else:
            source_ref = f"langfuse:trace:{score.get('traceId')}"
        name = score.get("name") or "langfuse_eval"
        value = score.get("value")
        comment = str(score.get("comment") or "").strip()
        title = f"Langfuse eval {name}={value}"
        body = comment or f"Langfuse score {name} value={value} source={source_ref}"
        return {
            "source_ref": source_ref,
            "title": title,
            "body": body,
            "raw": {
                "score_id": score.get("id"),
                "trace_id": score.get("traceId"),
                "name": name,
                "value": value,
            },
        }
    usable_traces = [item for item in traces if not _is_agent_cot_item(item) and not _is_builder_item(item)]
    if failed_only or not usable_traces:
        return None
    trace = usable_traces[0]
    trace_id = str(trace.get("id") or "").strip()
    if not trace_id:
        return None
    source_ref = f"langfuse:trace:{trace_id}"
    title = str(trace.get("name") or "Langfuse trace")
    return {
        "source_ref": source_ref,
        "title": title,
        "body": f"Langfuse trace {trace_id}",
        "raw": {"trace_id": trace_id, "name": trace.get("name")},
    }


def _redact_bundle_for_verifier(bundle: dict[str, Any]) -> dict[str, Any]:
    """Verifier may see sealed files + eval evidence, never Builder CoT or audit chatter."""
    redacted = dict(bundle)
    redacted.pop("audit", None)
    candidates = []
    for item in bundle.get("candidates") or []:
        if not isinstance(item, dict):
            continue
        candidates.append(
            {
                "id": item.get("id"),
                "digest": item.get("digest"),
                "files": item.get("files") or {},
                "summary": item.get("summary"),
            }
        )
    redacted["candidates"] = candidates
    evidence = []
    for item in bundle.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        cleaned = dict(item)
        arts = []
        for art in item.get("artifacts") or []:
            if not isinstance(art, dict):
                continue
            if _is_builder_item(art):
                continue
            art_clean = dict(art)
            for key in ("input", "output", "prompt", "completion", "generation", "cot", "chain_of_thought"):
                art_clean.pop(key, None)
            arts.append(art_clean)
        cleaned["artifacts"] = arts
        evidence.append(cleaned)
    redacted["evidence"] = evidence
    redacted["note"] = "Builder chain-of-thought is withheld from verifier export."
    return redacted


def _case_verified(kernel: Kernel, case: dict[str, Any]) -> bool:
    if case.get("verified_candidate_id"):
        verified = kernel.store.get("verified_candidates", case["verified_candidate_id"])
        if verified:
            return True
    gate_id = case.get("gate_report_id")
    if gate_id:
        report = kernel.store.get("gate_reports", gate_id)
        if report and report.get("verdict") == "VERIFIED":
            return True
    return case.get("state") == "verified"


def _draft_operations(kernel: Kernel, case_id: str) -> list[dict[str, Any]]:
    return [
        item
        for item in kernel.store.list("operations")
        if item.get("case_id") == case_id and item.get("kind") == "draft_pr"
    ]


@app.get("/ready")
def ready() -> dict:
    return {"kernel": "ok"}


@app.get("/health")
def health() -> dict:
    return {"kernel": "ok"}


@app.get("/v1/models")
@app.get("/v1/llm/models")
def llm_models() -> dict[str, Any]:
    return models_payload()


@app.post("/v1/chat/completions")
@app.post("/v1/llm/chat/completions")
async def llm_chat_completions(request: Request) -> Any:
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="JSON body required") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON object required")
    return proxy_chat(payload, {k: v for k, v in request.headers.items()})


class EvaluateBody(BaseModel):
    message: str
    session_id: str | None = None
    user_ref: str | None = None


@app.post("/v2/versionsets/{versionset_id}/evaluate")
def evaluate_versionset_endpoint(
    versionset_id: str,
    body: EvaluateBody,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """CaseLoop eval-harness entry: one probe against the exact immutable VersionSet."""
    from agentmed.evaluate import evaluate_versionset as run_evaluate
    from agentmed.evaluate import require_eval_token

    settings = load_settings()
    require_eval_token(settings, authorization)
    return run_evaluate(settings, versionset_id, body.message)


@app.get("/v2/versionsets/{versionset_id}")
def get_versionset_endpoint(
    versionset_id: str,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """CaseLoop eval-harness read: the VersionSet record bound by the registry."""
    from agentmed.evaluate import get_versionset_record
    from agentmed.evaluate import require_eval_token

    settings = load_settings()
    require_eval_token(settings, authorization)
    return get_versionset_record(settings, versionset_id)


class IngestBody(BaseModel):
    url: str
    title: str | None = None
    summary: str | None = None
    expected_behavior: str | None = None
    badcase_input: str | None = None
    judge: str | None = None


class LangfuseIngestBody(BaseModel):
    min_score: float | None = None
    failed_only: bool = True
    window: str | None = None


class EvidenceBody(BaseModel):
    kind: str
    summary: str
    artifacts: list[Any] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


class ObservabilityBody(BaseModel):
    url: str | None = None


class LangfuseEvidenceBody(BaseModel):
    case_id: str
    limit: int = 50
    name: str | None = None
    role: str | None = None


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


@app.post("/v1/signals/ingest-langfuse")
def ingest_langfuse(
    body: LangfuseIngestBody = Body(default_factory=LangfuseIngestBody),
    x_agentmed_principal: str | None = Header(default=None, alias="X-AgentMED-Principal"),
) -> dict[str, Any]:
    principal = _require(x_agentmed_principal, {ROLE_PRINCIPALS["intake"], ROLE_PRINCIPALS["lead"]})
    params = body
    try:
        payload = _query_langfuse(
            min_score=params.min_score,
            failed_only=params.failed_only,
            window=params.window,
        )
    except LangfuseUnavailable:
        return _langfuse_needs_context()
    picked = _pick_langfuse_eval(payload, min_score=params.min_score, failed_only=params.failed_only)
    if not picked:
        return _langfuse_needs_context()
    kernel = _kernel()
    app_row = kernel.ensure_app(slug="kotaemon", name="kotaemon", repo=KOTAEMON_REPO)
    signal = kernel.ingest_signal(
        principal=principal,
        source_type="langfuse_eval",
        source_ref=picked["source_ref"],
        title=picked["title"],
        body=picked["body"],
        application_id=app_row["id"],
        raw=picked["raw"],
    )
    case = kernel.open_case(principal=principal, signal=signal, application=app_row)
    return {
        "status": "ok",
        "needs_context": False,
        "missing": [],
        "signal": signal,
        "case": case,
        "signals": [signal],
        "cases": [case],
    }


@app.post("/v1/cases/{case_id}/evidence")
def add_evidence(
    case_id: str,
    body: EvidenceBody,
    x_agentmed_principal: str | None = Header(default=None, alias="X-AgentMED-Principal"),
) -> dict[str, Any]:
    principal = _require(
        x_agentmed_principal,
        {
            ROLE_PRINCIPALS["investigator"],
            ROLE_PRINCIPALS["attribution"],
            ROLE_PRINCIPALS["lead"],
        },
    )
    kernel = _kernel()
    try:
        kernel._case(case_id)
        return kernel.add_evidence(
            principal=principal,
            case_id=case_id,
            kind=body.kind,
            summary=body.summary,
            artifacts=list(body.artifacts),
            missing=list(body.missing),
        )
    except KernelError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/v1/cases/{case_id}/langfuse-traces")
def langfuse_traces(
    case_id: str,
    role: str | None = None,
    x_agentmed_principal: str | None = Header(default=None, alias="X-AgentMED-Principal"),
) -> dict[str, Any]:
    principal = _require(
        x_agentmed_principal,
        {
            ROLE_PRINCIPALS["investigator"],
            ROLE_PRINCIPALS["attribution"],
            ROLE_PRINCIPALS["verifier"],
            ROLE_PRINCIPALS["lead"],
        },
    )
    inferred = _PRINCIPAL_TO_TRACE_ROLE.get(principal, "investigator")
    effective_role = (role or inferred).strip().lower()
    if effective_role not in _TRACE_ROLES:
        raise HTTPException(status_code=400, detail="role must be investigator|attribution|verifier|lead")
    kernel = _kernel()
    try:
        kernel._case(case_id)
    except KernelError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        payload = _query_langfuse(case_id=case_id, failed_only=False)
    except LangfuseUnavailable:
        return {"needs_context": True, "missing": ["target_app_langfuse_traces"], "traces": []}
    traces = [item for item in (payload.get("traces") or []) if isinstance(item, dict)]
    traces = partition_traces(traces)["target"]
    strip_builder = principal == ROLE_PRINCIPALS["verifier"] or effective_role == "verifier"
    viewer = ROLE_PRINCIPALS["verifier"] if strip_builder else principal
    cleaned = sanitize_traces(traces, viewer)
    if not cleaned:
        return {
            "status": "NEEDS_CONTEXT",
            "needs_context": True,
            "missing": ["target_app_langfuse_traces"],
            "traces": [],
        }
    return {
        "status": "ok",
        "needs_context": False,
        "missing": [],
        "traces": cleaned,
        "role": effective_role,
    }


@app.post("/v1/evidence/langfuse")
def evidence_langfuse(
    body: LangfuseEvidenceBody,
    x_agentmed_principal: str | None = Header(default=None, alias="X-AgentMED-Principal"),
) -> dict[str, Any]:
    traces_payload = langfuse_traces(
        body.case_id,
        role=body.role,
        x_agentmed_principal=x_agentmed_principal,
    )
    principal = x_agentmed_principal or ROLE_PRINCIPALS["investigator"]
    kernel = _kernel()
    traces = traces_payload.get("traces") or []
    missing = list(traces_payload.get("missing") or [])
    note = "Never forge spans. Never copy Builder chain-of-thought to Verifier."
    # Verifier may read sanitized traces but must not write investigator EvidenceReceipts.
    persist = principal in {ROLE_PRINCIPALS["investigator"], ROLE_PRINCIPALS["attribution"], ROLE_PRINCIPALS["lead"]}
    if traces_payload.get("needs_context") or not traces:
        receipt = None
        if persist:
            receipt = kernel.add_evidence(
                principal=principal,
                case_id=body.case_id,
                kind="langfuse_traces",
                summary="Langfuse traces missing or unreachable; NEEDS_CONTEXT. Do not forge spans.",
                artifacts=[],
                missing=missing or ["target_app_langfuse_traces"],
            )
        return {
            "status": "NEEDS_CONTEXT",
            "needs_context": True,
            "evidence": receipt,
            "traces": [],
            "note": note,
        }
    receipt = None
    if persist:
        receipt = kernel.add_evidence(
            principal=principal,
            case_id=body.case_id,
            kind="langfuse_traces",
            summary=f"Langfuse traces ({len(traces)}) for {principal}",
            artifacts=[{"type": "langfuse_trace", "id": item.get("id"), "name": item.get("name")} for item in traces],
            missing=[],
        )
    return {"status": "ok", "needs_context": False, "traces": traces, "evidence": receipt, "note": note}


@app.post("/v1/langfuse/provision")
def provision_langfuse(
    x_agentmed_principal: str | None = Header(default=None, alias="X-AgentMED-Principal"),
) -> dict[str, Any]:
    _require(
        x_agentmed_principal,
        {
            ROLE_PRINCIPALS["investigator"],
            ROLE_PRINCIPALS["lead"],
            ROLE_PRINCIPALS["intake"],
        },
    )
    settings = load_settings()
    refs = provision_refs(settings.langfuse_host, keys_configured=settings.langfuse_enabled)
    records = harvest_prompts()
    summary = catalog_summary(records)
    upsert: dict[str, Any] = {
        "status": "skipped",
        "reason": "langfuse_keys_missing",
        "upserted": [],
        "failed": [],
        "upserted_count": 0,
        "failed_count": 0,
    }
    if settings.langfuse_enabled:
        upsert = upsert_prompts(
            host=settings.langfuse_host,
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            records=records,
        )
    governance = {
        "prompt_count": summary["count"],
        "prompt_names": summary["names"],
        "llm_proxy": "POST /v1/chat/completions",
        "upsert_status": upsert.get("status"),
        "upserted_count": upsert.get("upserted_count", len(upsert.get("upserted") or [])),
        "failed_count": upsert.get("failed_count", len(upsert.get("failed") or [])),
    }
    try:
        _query_langfuse(failed_only=False)
        return {
            "status": "ok",
            "needs_context": False,
            "refs": refs,
            "governance": governance,
        }
    except LangfuseUnavailable as exc:
        return {
            "status": "NEEDS_CONTEXT",
            "needs_context": True,
            "reason": "langfuse_unreachable",
            "detail": str(exc),
            "refs": refs,
            "governance": governance,
        }


def _is_builder_prompt(item: dict[str, Any]) -> bool:
    blob = f"{item.get('name') or ''} {item.get('role') or ''} {item.get('source') or ''}".lower()
    return "builder" in blob or "propose-candidate" in blob


def _governance_prompt_rows(principal: str) -> list[dict[str, Any]]:
    hide_builder = "verifier" in principal.lower()
    rows: list[dict[str, Any]] = []
    for item in harvest_prompts():
        row = {
            "name": item["name"],
            "role": item["role"],
            "kind": item["kind"],
            "source": item["source"],
            "tags": item.get("tags") or [],
        }
        if hide_builder and _is_builder_prompt(item):
            row["prompt"] = None
            row["redacted"] = True
        else:
            row["prompt"] = item["prompt"]
            row["redacted"] = False
        rows.append(row)
    return rows


@app.get("/v1/governance/prompts")
def governance_prompts(
    x_agentmed_principal: str | None = Header(default=None, alias="X-AgentMED-Principal"),
) -> dict[str, Any]:
    principal = _require(x_agentmed_principal, _GOVERNANCE_READERS)
    rows = _governance_prompt_rows(principal)
    return {
        "status": "ok",
        "plane": "governance",
        "count": len(rows),
        "names": [item["name"] for item in rows],
        "prompts": rows,
        "note": "Static templates from the AgentMED pack. Live LLM calls are POST /v1/chat/completions → Langfuse.",
    }


@app.get("/v1/governance/traces")
def governance_traces(
    x_agentmed_principal: str | None = Header(default=None, alias="X-AgentMED-Principal"),
) -> dict[str, Any]:
    principal = _require(x_agentmed_principal, _GOVERNANCE_READERS)
    try:
        payload = _query_langfuse(failed_only=False)
    except LangfuseUnavailable as exc:
        return {
            "status": "NEEDS_CONTEXT",
            "needs_context": True,
            "missing": ["agentmed_governance_traces"],
            "reason": str(exc),
            "traces": [],
        }
    traces = [item for item in (payload.get("traces") or []) if isinstance(item, dict)]
    traces = partition_traces(traces)["governance"]
    cleaned = sanitize_traces(traces, principal)
    if not cleaned:
        return {
            "status": "NEEDS_CONTEXT",
            "needs_context": True,
            "missing": ["agentmed_governance_traces"],
            "traces": [],
        }
    return {
        "status": "ok",
        "needs_context": False,
        "missing": [],
        "plane": "governance",
        "traces": cleaned,
        "note": "Never copy Builder chain-of-thought to Verifier.",
    }


@app.post("/v1/cases/{case_id}/observability-connect")
def observability_connect(
    case_id: str,
    body: ObservabilityBody | None = None,
    x_agentmed_principal: str | None = Header(default=None, alias="X-AgentMED-Principal"),
) -> dict[str, Any]:
    principal = _require(
        x_agentmed_principal,
        {
            ROLE_PRINCIPALS["investigator"],
            ROLE_PRINCIPALS["attribution"],
            ROLE_PRINCIPALS["lead"],
        },
    )
    body = body or ObservabilityBody()
    kernel = _kernel()
    try:
        kernel._case(case_id)
    except KernelError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    probe = probe_monitor(body.url)
    receipt = kernel.add_evidence(
        principal=principal,
        case_id=case_id,
        kind="enterprise_monitor",
        summary=str(probe["summary"]),
        artifacts=(
            [{"type": "monitor_probe", "url_ref": body.url or "", "connected": probe["connected"]}]
            if body.url
            else []
        ),
        missing=list(probe["missing"]),
    )
    return {"status": "ok" if probe["connected"] else "degraded", "probe": probe, "evidence": receipt}


@app.post("/v1/cases/{case_id}/draft-pr")
def draft_pr(
    case_id: str,
    x_agentmed_principal: str | None = Header(default=None, alias="X-AgentMED-Principal"),
) -> dict[str, Any]:
    _require(x_agentmed_principal, {ROLE_PRINCIPALS["lead"], ROLE_PRINCIPALS["controller"]})
    settings = load_settings()
    kernel = _kernel()
    try:
        case = kernel._case(case_id)
        if not _case_verified(kernel, case):
            raise KernelError("draft-pr requires VerifiedCandidate / VERIFIED gate")
        existing = _draft_operations(kernel, case_id)
        if existing:
            return {
                "reused": True,
                "patch": existing[-1].get("receipt"),
                "operations": existing,
            }
        candidate_id = case.get("candidate_id")
        if not candidate_id:
            raise KernelError("no candidate")
        candidate = kernel.store.get("candidates", candidate_id)
        if not candidate:
            raise KernelError("candidate missing")
        runtime = Path(settings.agentmed_data_dir) / "runtime" / case_id
        drafted = write_draft_patch(kernel, case_id, candidate, runtime)
        return {
            "reused": False,
            "patch": drafted["patch"],
            "operations": [drafted["operation"]],
        }
    except KernelError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
def get_evidence(
    case_id: str,
    x_agentmed_principal: str | None = Header(default=None, alias="X-AgentMED-Principal"),
) -> dict:
    try:
        bundle = _kernel().export_case(case_id)
    except KernelError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if x_agentmed_principal == ROLE_PRINCIPALS["verifier"]:
        return _redact_bundle_for_verifier(bundle)
    return bundle
