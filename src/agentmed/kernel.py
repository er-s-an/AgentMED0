from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from agentmed.ids import digest, new_id, utcnow
from agentmed.store import Store

ASSURANCE_VALUES = frozenset(
    {
        "IMMUTABLE_DIGEST",
        "PROVIDER_VERSION",
        "MUTABLE_ALIAS",
        "OBSERVED_ONLY",
        "UNKNOWN",
    }
)
GATE_PURPOSES = frozenset({"CANDIDATE_VERIFICATION", "RELEASE_AUTHORIZATION"})
CONFLICT_CODES = frozenset(
    {
        "NEEDS_ACCEPTANCE_CRITERIA",
        "NEEDS_EPISODE_SNAPSHOT",
        "NEEDS_RELEASE_PLAN",
        "NEEDS_RELEASE_AUTHORIZATION",
        "NEEDS_RELEASE_APPROVAL",
        "WORK_ORDER_CONSUMED",
        "WORK_ORDER_EXPIRED",
        "WORK_ORDER_DIGEST_MISMATCH",
    }
)

CASE_STATES = {
    "drafted",
    "awaiting_acceptance",
    "investigating",
    "proposing",
    "verifying",
    "verified",
    "rejected",
    "inconclusive",
    "shadow_applied",
    "rolled_back",
    "closed",
}

ROLE_PRINCIPALS = {
    "intake": "agent:intake",
    "lead": "agent:lead",
    "investigator": "agent:investigator",
    "attribution": "agent:attribution",
    "builder": "agent:builder",
    "verifier": "agent:verifier",
    "curator": "agent:curator",
    "controller": "controller:agentmed",
    "human": "human:cli",
}


class KernelError(RuntimeError):
    def __init__(self, message: str, *, code: str | None = None, extra: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        token = (code or message.split()[0] if message else "KERNEL_ERROR").strip()
        self.code = token if token in CONFLICT_CODES or (token.isupper() and "_" in token) else "KERNEL_ERROR"
        self.extra = extra or {}


class Kernel:
    """Deterministic control plane. Agents propose; this object owns state."""

    def __init__(self, store: Store) -> None:
        self.store = store

    def audit(self, action: str, principal: str, subject: str, payload: dict[str, Any]) -> None:
        event = {
            "id": new_id("aud"),
            "at": utcnow(),
            "action": action,
            "principal": principal,
            "subject": subject,
            "digest": digest(payload),
            "payload": payload,
        }
        self.store.put("audit", event)

    def ensure_app(self, slug: str, name: str, repo: str) -> dict[str, Any]:
        existing = [item for item in self.store.list("applications") if item.get("slug") == slug]
        if existing:
            return existing[0]
        app = {
            "id": new_id("app"),
            "slug": slug,
            "name": name,
            "repo": repo,
            "created_at": utcnow(),
        }
        self.store.put("applications", app)
        self.audit("application.upsert", ROLE_PRINCIPALS["controller"], app["id"], app)
        return app

    def ingest_signal(
        self,
        *,
        principal: str,
        source_type: str,
        source_ref: str,
        title: str,
        body: str,
        application_id: str,
        raw: dict[str, Any],
    ) -> dict[str, Any]:
        source_digest = digest({"source_ref": source_ref, "body": body})
        for signal in self.store.list("signals"):
            if signal.get("source_digest") == source_digest:
                return signal
        signal = {
            "id": new_id("sig"),
            "source_type": source_type,
            "source_ref": source_ref,
            "title": title,
            "body": body,
            "application_id": application_id,
            "source_digest": source_digest,
            "raw": raw,
            "created_at": utcnow(),
            "created_by": principal,
        }
        self.store.put("signals", signal)
        self.audit("signal.ingest", principal, signal["id"], {"source_ref": source_ref})
        return signal

    def open_case(self, *, principal: str, signal: dict[str, Any], application: dict[str, Any]) -> dict[str, Any]:
        for existing in self.store.list("cases"):
            if existing.get("signal_id") == signal["id"] and existing.get("state") != "closed":
                return existing
        case = {
            "id": new_id("case"),
            "application_id": application["id"],
            "signal_id": signal["id"],
            "title": signal["title"],
            "state": "awaiting_acceptance",
            "created_at": utcnow(),
            "created_by": principal,
            "acceptance_spec_id": None,
            "version_snapshot_id": None,
            "candidate_id": None,
            "candidate_ids": [],
            "gate_report_id": None,
            "verified_candidate_id": None,
            "regression_asset_id": None,
            "acceptance_draft_id": None,
            "episode_snapshot_id": None,
            "release_plan_id": None,
            "work_order_id": None,
            "approval_id": None,
            "work_order_generation": 0,
            "last_investigation_conclusion": None,
            "notes": [],
        }
        self.store.put("cases", case)
        self.audit("case.open", principal, case["id"], {"signal_id": signal["id"]})
        return case

    def _case(self, case_id: str) -> dict[str, Any]:
        case = self.store.get("cases", case_id)
        if not case:
            raise KernelError(f"unknown case {case_id}")
        return case

    def _set_state(self, case: dict[str, Any], state: str, principal: str) -> dict[str, Any]:
        if state not in CASE_STATES:
            raise KernelError(f"illegal state {state}")
        case["state"] = state
        case["updated_at"] = utcnow()
        self.store.put("cases", case)
        self.audit("case.state", principal, case["id"], {"state": state})
        return case

    def propose_acceptance(
        self,
        *,
        principal: str,
        case_id: str,
        expected_behavior: str,
        badcase_input: str,
        judge: str,
    ) -> dict[str, Any]:
        case = self._case(case_id)
        draft = {
            "id": new_id("draft"),
            "case_id": case_id,
            "expected_behavior": expected_behavior,
            "badcase_input": badcase_input,
            "judge": judge,
            "proposed_by": principal,
            "proposed_at": utcnow(),
        }
        draft["digest"] = digest(draft)
        self.store.put("acceptance_drafts", draft)
        case["acceptance_draft_id"] = draft["id"]
        self.store.put("cases", case)
        self.audit("acceptance.propose", principal, draft["id"], {"digest": draft["digest"]})
        return draft

    def confirm_acceptance(
        self,
        *,
        principal: str,
        case_id: str,
        expected_behavior: str,
        badcase_input: str,
        judge: str,
        confirmed_via: str = "human",
    ) -> dict[str, Any]:
        if not principal.startswith("human:"):
            raise KernelError("AcceptanceSpec must be confirmed by a human principal")
        if not str(expected_behavior or "").strip() or not str(badcase_input or "").strip():
            raise KernelError("NEEDS_ACCEPTANCE_CRITERIA")
        case = self._case(case_id)
        spec = {
            "id": new_id("spec"),
            "case_id": case_id,
            "expected_behavior": expected_behavior.strip(),
            "badcase_input": badcase_input.strip(),
            "judge": (judge or "").strip(),
            "confirmed_by": principal,
            "confirmed_via": confirmed_via,
            "confirmed_at": utcnow(),
        }
        spec["digest"] = digest(spec)
        self.store.put("acceptance_specs", spec)
        case["acceptance_spec_id"] = spec["id"]
        self._set_state(case, "investigating", principal)
        self.audit("acceptance.confirm", principal, spec["id"], {"digest": spec["digest"]})
        return spec

    def bind_version_snapshot(
        self,
        *,
        principal: str,
        case_id: str,
        manifest: dict[str, Any],
    ) -> dict[str, Any]:
        case = self._case(case_id)
        normalized = _normalize_manifest(manifest)
        snapshot = {
            "id": new_id("ver"),
            "case_id": case_id,
            "manifest": normalized,
            "created_by": principal,
            "created_at": utcnow(),
        }
        snapshot["digest"] = digest(normalized)
        self.store.put("version_snapshots", snapshot)
        case["version_snapshot_id"] = snapshot["id"]
        self.store.put("cases", case)
        self.audit("version.bind", principal, snapshot["id"], {"digest": snapshot["digest"]})
        return snapshot

    def seal_episode(
        self,
        *,
        principal: str,
        case_id: str,
        coverage: dict[str, Any] | None = None,
        extra_missing: list[str] | None = None,
    ) -> dict[str, Any]:
        case = self._case(case_id)
        existing_id = case.get("episode_snapshot_id")
        if existing_id:
            existing = self.store.get("episode_snapshots", existing_id)
            if existing and existing.get("sealed"):
                return existing
        receipts = [item for item in self.store.list("evidence") if item.get("case_id") == case_id]
        missing: list[str] = []
        for item in receipts:
            missing.extend(str(token) for token in (item.get("missing") or []) if token)
        missing.extend(str(token) for token in (extra_missing or []) if token)
        snapshot = {
            "id": new_id("eps"),
            "case_id": case_id,
            "evidence_ids": [item["id"] for item in receipts],
            "coverage": coverage or {},
            "missing": sorted(set(missing)),
            "sealed": True,
            "sealed_by": principal,
            "sealed_at": utcnow(),
        }
        snapshot["digest"] = digest(
            {
                "evidence_ids": snapshot["evidence_ids"],
                "coverage": snapshot["coverage"],
                "missing": snapshot["missing"],
            }
        )
        self.store.put("episode_snapshots", snapshot)
        case["episode_snapshot_id"] = snapshot["id"]
        self.store.put("cases", case)
        self.audit("episode.seal", principal, snapshot["id"], {"digest": snapshot["digest"]})
        return snapshot

    def add_evidence(
        self,
        *,
        principal: str,
        case_id: str,
        kind: str,
        summary: str,
        artifacts: list[dict[str, Any]],
        missing: list[str],
    ) -> dict[str, Any]:
        receipt = {
            "id": new_id("evd"),
            "case_id": case_id,
            "kind": kind,
            "summary": summary,
            "artifacts": artifacts,
            "missing": missing,
            "integrity": "partial" if missing else "complete",
            "created_by": principal,
            "created_at": utcnow(),
        }
        receipt["digest"] = digest(receipt)
        self.store.put("evidence", receipt)
        self.audit("evidence.add", principal, receipt["id"], {"kind": kind})
        return receipt

    def add_investigation(
        self,
        *,
        principal: str,
        case_id: str,
        hypothesis: str,
        conclusion: str,
        uncertainty: str,
        force_skip: bool = False,
    ) -> dict[str, Any]:
        if conclusion not in {"SUPPORTED", "REFUTED", "INCONCLUSIVE", "CONFOUNDED"}:
            raise KernelError("invalid investigation conclusion")
        report = {
            "id": new_id("inv"),
            "case_id": case_id,
            "hypothesis": hypothesis,
            "conclusion": conclusion,
            "uncertainty": uncertainty,
            "force_skip": force_skip,
            "created_by": principal,
            "created_at": utcnow(),
        }
        self.store.put("investigations", report)
        case = self._case(case_id)
        case["last_investigation_conclusion"] = conclusion
        self.store.put("cases", case)
        if conclusion == "SUPPORTED" or force_skip:
            self._set_state(case, "proposing", principal)
        else:
            self.store.put("cases", case)
            self.audit("investigation.hold", principal, report["id"], {"conclusion": conclusion})
        self.audit("investigation.add", principal, report["id"], {"conclusion": conclusion})
        return report

    def submit_candidate(
        self,
        *,
        principal: str,
        case_id: str,
        summary: str,
        diff: str,
        files: dict[str, str],
        risk: str,
    ) -> dict[str, Any]:
        if principal != ROLE_PRINCIPALS["builder"]:
            raise KernelError("only the builder principal may submit a candidate")
        case = self._case(case_id)
        if not case.get("acceptance_spec_id"):
            raise KernelError("cannot submit a candidate without AcceptanceSpec")
        candidate = {
            "id": new_id("can"),
            "case_id": case_id,
            "base_snapshot_id": case.get("version_snapshot_id"),
            "summary": summary,
            "diff": diff,
            "files": files,
            "risk": risk,
            "created_by": principal,
            "created_at": utcnow(),
            "sealed": True,
        }
        candidate["digest"] = digest({"diff": diff, "files": files})
        self.store.put("candidates", candidate)
        history = list(case.get("candidate_ids") or [])
        history.append(candidate["id"])
        case["candidate_ids"] = history
        case["candidate_id"] = candidate["id"]
        self._set_state(case, "verifying", principal)
        return candidate

    def submit_gate(
        self,
        *,
        principal: str,
        case_id: str,
        verdict: str,
        evidence: dict[str, Any],
        false_pass_risk: str,
        purpose: str = "CANDIDATE_VERIFICATION",
    ) -> dict[str, Any]:
        if purpose not in GATE_PURPOSES:
            raise KernelError("invalid gate purpose")
        if purpose == "RELEASE_AUTHORIZATION":
            raise KernelError("use authorize_release for RELEASE_AUTHORIZATION")
        if principal != ROLE_PRINCIPALS["verifier"]:
            raise KernelError("only the verifier principal may submit a GateReport")
        if verdict not in {"VERIFIED", "REJECTED", "INCONCLUSIVE", "ERROR"}:
            raise KernelError("invalid gate verdict")
        case = self._case(case_id)
        candidate_id = case.get("candidate_id")
        if not candidate_id:
            raise KernelError("no candidate to verify")
        candidate = self.store.get("candidates", candidate_id)
        if candidate and candidate.get("created_by") == principal:
            raise KernelError("builder cannot verify their own candidate")
        report = {
            "id": new_id("gate"),
            "case_id": case_id,
            "candidate_id": candidate_id,
            "purpose": purpose,
            "verdict": verdict,
            "evidence": evidence,
            "false_pass_risk": false_pass_risk,
            "created_by": principal,
            "created_at": utcnow(),
        }
        report["digest"] = digest(report)
        self.store.put("gate_reports", report)
        case["gate_report_id"] = report["id"]
        if verdict == "VERIFIED":
            verified = {
                "id": new_id("vc"),
                "case_id": case_id,
                "candidate_id": candidate_id,
                "gate_report_id": report["id"],
                "deployed": False,
                "status": "NOT_DEPLOYED",
                "created_at": utcnow(),
            }
            self.store.put("verified_candidates", verified)
            case["verified_candidate_id"] = verified["id"]
            self._set_state(case, "verified", principal)
        elif verdict == "REJECTED":
            self._set_state(case, "rejected", principal)
        elif verdict == "INCONCLUSIVE":
            self._set_state(case, "inconclusive", principal)
        else:
            self._set_state(case, "inconclusive", principal)
        return report

    def record_operation(
        self,
        *,
        principal: str,
        case_id: str,
        kind: str,
        desired: str,
        observed: str,
        receipt: str,
        status: str,
    ) -> dict[str, Any]:
        op = {
            "id": new_id("op"),
            "case_id": case_id,
            "kind": kind,
            "desired": desired,
            "observed": observed,
            "receipt": receipt,
            "status": status,
            "created_by": principal,
            "created_at": utcnow(),
        }
        self.store.put("operations", op)
        if kind == "shadow_apply":
            self._set_state(self._case(case_id), "shadow_applied", principal)
        if kind == "rollback":
            self._set_state(self._case(case_id), "rolled_back", principal)
        self.audit("operation.record", principal, op["id"], {"kind": kind, "status": status})
        return op

    def close_with_asset(
        self,
        *,
        principal: str,
        case_id: str,
        summary: str,
        probes: list[str],
        lessons: str,
    ) -> dict[str, Any]:
        case = self._case(case_id)
        asset = {
            "id": new_id("reg"),
            "case_id": case_id,
            "summary": summary,
            "probes": probes,
            "lessons": lessons,
            "acceptance_spec_id": case.get("acceptance_spec_id"),
            "candidate_id": case.get("candidate_id"),
            "gate_report_id": case.get("gate_report_id"),
            "created_by": principal,
            "created_at": utcnow(),
        }
        self.store.put("regression_assets", asset)
        case["regression_asset_id"] = asset["id"]
        self._set_state(case, "closed", principal)
        return asset

    def prior_regression_assets(self, case_id: str) -> list[dict[str, Any]]:
        case = self._case(case_id)
        app_id = case.get("application_id")
        closed_ids = {
            item["id"]
            for item in self.store.list("cases")
            if item.get("application_id") == app_id
            and item.get("state") == "closed"
            and item.get("id") != case_id
        }
        assets: list[dict[str, Any]] = []
        for asset in self.store.list("regression_assets"):
            if asset.get("case_id") not in closed_ids:
                continue
            assets.append(
                {
                    "id": asset.get("id"),
                    "case_id": asset.get("case_id"),
                    "probes": list(asset.get("probes") or []),
                }
            )
        return assets

    def create_release_plan(
        self,
        *,
        principal: str,
        case_id: str,
        rollout: str = "local_shadow",
        rollback: str = "restore_base",
        observed: str = "reread_files",
    ) -> dict[str, Any]:
        case = self._case(case_id)
        if case.get("state") != "verified" or not case.get("verified_candidate_id"):
            raise KernelError("release plan requires VerifiedCandidate / NOT DEPLOYED")
        plan = {
            "id": new_id("rpl"),
            "case_id": case_id,
            "candidate_id": case.get("candidate_id"),
            "verified_candidate_id": case.get("verified_candidate_id"),
            "rollout": rollout,
            "rollback": rollback,
            "observed": observed,
            "created_by": principal,
            "created_at": utcnow(),
        }
        plan["digest"] = digest(plan)
        self.store.put("release_plans", plan)
        case["release_plan_id"] = plan["id"]
        self.store.put("cases", case)
        self.audit("release_plan.create", principal, plan["id"], {"digest": plan["digest"]})
        return plan

    def authorize_release(self, *, principal: str, case_id: str) -> dict[str, Any]:
        if principal not in {ROLE_PRINCIPALS["lead"], ROLE_PRINCIPALS["verifier"], ROLE_PRINCIPALS["controller"]}:
            raise KernelError("only lead or verifier may submit RELEASE_AUTHORIZATION")
        case = self._case(case_id)
        if case.get("state") != "verified":
            raise KernelError("RELEASE_AUTHORIZATION requires verified state")
        plan = self.store.get("release_plans", case.get("release_plan_id") or "")
        if not plan:
            raise KernelError("NEEDS_RELEASE_PLAN")
        snapshot = self.store.get("version_snapshots", case.get("version_snapshot_id") or "") or {}
        episode = self.store.get("episode_snapshots", case.get("episode_snapshot_id") or "") or {}
        candidate = self.store.get("candidates", case.get("candidate_id") or "") or {}
        report = {
            "id": new_id("gate"),
            "case_id": case_id,
            "candidate_id": case.get("candidate_id"),
            "purpose": "RELEASE_AUTHORIZATION",
            "verdict": "AUTHORIZED",
            "evidence": {
                "candidate_digest": candidate.get("digest"),
                "plan_digest": plan.get("digest"),
                "snapshot_digest": snapshot.get("digest"),
                "episode_digest": episode.get("digest"),
            },
            "false_pass_risk": "authorization binds exact candidate + plan + snapshot digests",
            "created_by": principal,
            "created_at": utcnow(),
        }
        report["digest"] = digest(report)
        self.store.put("gate_reports", report)
        generation = int(case.get("work_order_generation") or 0) + 1
        expires = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        work_order = {
            "id": new_id("wo"),
            "case_id": case_id,
            "plan_id": plan["id"],
            "gate_report_id": report["id"],
            "candidate_id": case.get("candidate_id"),
            "verified_candidate_id": case.get("verified_candidate_id"),
            "snapshot_digest": snapshot.get("digest"),
            "episode_digest": episode.get("digest"),
            "plan_digest": plan.get("digest"),
            "nonce": new_id("nonce"),
            "generation": generation,
            "target": "local_shadow",
            "expires_at": expires,
            "consumed_at": None,
            "status": "open",
            "created_by": principal,
            "created_at": utcnow(),
        }
        work_order["digest"] = digest(
            {
                "nonce": work_order["nonce"],
                "generation": generation,
                "candidate_id": work_order["candidate_id"],
                "plan_digest": work_order["plan_digest"],
                "snapshot_digest": work_order["snapshot_digest"],
            }
        )
        self.store.put("work_orders", work_order)
        case["work_order_generation"] = generation
        case["work_order_id"] = work_order["id"]
        case["approval_id"] = None
        self.store.put("cases", case)
        self.audit("release.authorize", principal, report["id"], {"work_order": work_order["id"]})
        return {"gate_report": report, "work_order": work_order}

    def approve_work_order(
        self,
        *,
        principal: str,
        case_id: str,
        work_order_id: str,
        decision: str = "approve",
    ) -> dict[str, Any]:
        if not principal.startswith("human:"):
            raise KernelError("Approval must be confirmed by a human principal")
        if decision != "approve":
            raise KernelError("only approve is supported for local shadow")
        case = self._case(case_id)
        work_order = self.store.get("work_orders", work_order_id)
        if not work_order or work_order.get("case_id") != case_id:
            raise KernelError("unknown work order")
        if work_order.get("consumed_at"):
            raise KernelError("WORK_ORDER_CONSUMED")
        if _expired(work_order.get("expires_at")):
            raise KernelError("WORK_ORDER_EXPIRED")
        approval = {
            "id": new_id("apr"),
            "case_id": case_id,
            "work_order_id": work_order["id"],
            "work_order_digest": work_order.get("digest"),
            "decision": decision,
            "approved_by": principal,
            "approved_at": utcnow(),
        }
        approval["digest"] = digest(approval)
        self.store.put("approvals", approval)
        case["approval_id"] = approval["id"]
        self.store.put("cases", case)
        self.audit("approval.grant", principal, approval["id"], {"work_order": work_order["id"]})
        return approval

    def unused_approval(self, case_id: str) -> dict[str, Any] | None:
        case = self._case(case_id)
        approval = self.store.get("approvals", case.get("approval_id") or "")
        if not approval:
            return None
        work_order = self.store.get("work_orders", approval.get("work_order_id") or "")
        if not work_order or work_order.get("consumed_at"):
            return None
        if work_order.get("digest") != approval.get("work_order_digest"):
            return None
        if _expired(work_order.get("expires_at")):
            return None
        return {"approval": approval, "work_order": work_order}

    def require_unused_approval(self, case_id: str) -> dict[str, Any]:
        found = self.unused_approval(case_id)
        if not found:
            if not self.store.get("release_plans", self._case(case_id).get("release_plan_id") or ""):
                raise KernelError("NEEDS_RELEASE_PLAN")
            if not self.store.get("work_orders", self._case(case_id).get("work_order_id") or ""):
                raise KernelError("NEEDS_RELEASE_AUTHORIZATION")
            raise KernelError("NEEDS_RELEASE_APPROVAL")
        return found

    def consume_work_order(self, *, principal: str, work_order_id: str) -> dict[str, Any]:
        work_order = self.store.get("work_orders", work_order_id)
        if not work_order:
            raise KernelError("unknown work order")
        if work_order.get("consumed_at"):
            raise KernelError("WORK_ORDER_CONSUMED")
        if _expired(work_order.get("expires_at")):
            raise KernelError("WORK_ORDER_EXPIRED")
        work_order["consumed_at"] = utcnow()
        work_order["status"] = "consumed"
        work_order["consumed_by"] = principal
        self.store.put("work_orders", work_order)
        self.audit("work_order.consume", principal, work_order["id"], {"nonce": work_order.get("nonce")})
        return work_order

    def next_actions(self, case_id: str) -> list[dict[str, Any]]:
        case = self._case(case_id)
        state = case.get("state")
        cid = case_id
        if state == "awaiting_acceptance":
            return [
                _next(
                    "NEEDS_ACCEPTANCE_CRITERIA",
                    "human:*",
                    f"POST /v1/cases/{cid}/accept",
                    "A human must confirm expected behavior. Adapter defaults are a draft, not the truth.",
                    missing=["expected_behavior", "badcase_input"],
                    role="human",
                )
            ]
        if state == "investigating" and case.get("last_investigation_conclusion") in {
            "INCONCLUSIVE",
            "CONFOUNDED",
        }:
            return [
                _next(
                    "NEEDS_EVIDENCE",
                    ROLE_PRINCIPALS["investigator"],
                    f"POST /v1/cases/{cid}/investigate",
                    "Investigation was INCONCLUSIVE or CONFOUNDED. Stay here and add evidence; do not propose yet.",
                    missing=["supporting_evidence"],
                    skill="bind-version-snapshot",
                    role="investigator",
                )
            ]
        if state == "investigating" and not case.get("version_snapshot_id"):
            return [
                _next(
                    "NEEDS_VERSION_SNAPSHOT",
                    ROLE_PRINCIPALS["investigator"],
                    f"POST /v1/cases/{cid}/investigate",
                    "Bind a VersionSet with component assurance before attribution.",
                    missing=["version_snapshot"],
                    skill="bind-version-snapshot",
                    role="investigator",
                )
            ]
        if state == "investigating":
            return [
                _next(
                    "NEEDS_ATTRIBUTION",
                    ROLE_PRINCIPALS["attribution"],
                    f"POST /v1/cases/{cid}/attribute",
                    "Record a SUPPORTED investigation, or stay and collect more evidence.",
                    skill="attribute-skip",
                    role="attribution",
                )
            ]
        if state in {"proposing", "rejected"}:
            return [
                _next(
                    "NEEDS_CANDIDATE",
                    ROLE_PRINCIPALS["builder"],
                    f"POST /v1/cases/{cid}/candidates",
                    "Builder submits sealed files. The review console will not post a golden patch.",
                    skill="propose-candidate",
                    role="builder",
                )
            ]
        if state == "verifying":
            missing = [] if case.get("episode_snapshot_id") else ["episode_snapshot"]
            return [
                _next(
                    "NEEDS_CANDIDATE_VERIFICATION" if not missing else "NEEDS_EPISODE_SNAPSHOT",
                    ROLE_PRINCIPALS["verifier"],
                    f"POST /v1/cases/{cid}/verify",
                    "Gate purpose is CANDIDATE_VERIFICATION only. Seal an EpisodeSnapshot first.",
                    missing=missing,
                    skill="independent-verify",
                    role="verifier",
                )
            ]
        if state == "verified":
            if not case.get("release_plan_id"):
                return [
                    _next(
                        "REQUEST_SHADOW_PLAN",
                        ROLE_PRINCIPALS["lead"],
                        f"POST /v1/cases/{cid}/release-plans",
                        "Verification is not authorization. Request a local-shadow ReleasePlan.",
                        skill="release-observe-rollback",
                        role="lead",
                    )
                ]
            if not case.get("work_order_id"):
                return [
                    _next(
                        "NEEDS_RELEASE_AUTHORIZATION",
                        ROLE_PRINCIPALS["lead"],
                        f"POST /v1/cases/{cid}/gates/release-authorization",
                        "Bind the exact candidate, plan, and snapshot digests into a WorkOrder.",
                        skill="release-observe-rollback",
                        role="lead",
                    )
                ]
            if not self.unused_approval(cid):
                return [
                    _next(
                        "NEEDS_RELEASE_APPROVAL",
                        "human:*",
                        f"POST /v1/cases/{cid}/approvals",
                        "A human must approve this WorkOrder before any local shadow drill.",
                        missing=["approval"],
                        role="human",
                    )
                ]
            return [
                _next(
                    "SHADOW_DRILL",
                    ROLE_PRINCIPALS["lead"],
                    f"POST /v1/cases/{cid}/shadow",
                    "Local shadow drill only. Not a production release. VerifiedCandidate stays NOT DEPLOYED.",
                    skill="release-observe-rollback",
                    role="lead",
                )
            ]
        if state == "shadow_applied":
            return [
                _next(
                    "SHADOW_ROLLBACK",
                    ROLE_PRINCIPALS["lead"],
                    f"POST /v1/cases/{cid}/shadow",
                    "Roll back the local shadow files and re-read observed state.",
                    skill="release-observe-rollback",
                    role="lead",
                )
            ]
        if state == "rolled_back":
            return [
                _next(
                    "CURATE_REGRESSION_ASSET",
                    ROLE_PRINCIPALS["curator"],
                    f"POST /v1/cases/{cid}/close",
                    "Close the case and keep probes for the next Gate.",
                    skill="curate-regression-asset",
                    role="curator",
                )
            ]
        if state == "inconclusive":
            return [
                _next(
                    "NEEDS_EVIDENCE",
                    ROLE_PRINCIPALS["investigator"],
                    f"POST /v1/cases/{cid}/investigate",
                    "Gate was INCONCLUSIVE. Collect evidence; do not treat this as verified.",
                    missing=["supporting_evidence"],
                    skill="bind-version-snapshot",
                    role="investigator",
                )
            ]
        return []

    def list_cases(self) -> list[dict[str, Any]]:
        return self.store.list("cases")

    def find_case_by_source_ref(self, source_ref: str) -> dict[str, Any] | None:
        signal_ids = {
            item["id"] for item in self.store.list("signals") if item.get("source_ref") == source_ref
        }
        if not signal_ids:
            return None
        matches = [
            case
            for case in self.store.list("cases")
            if case.get("signal_id") in signal_ids
        ]
        if not matches:
            return None
        return sorted(matches, key=lambda item: item.get("created_at") or "", reverse=True)[0]

    def export_case(self, case_id: str) -> dict[str, Any]:
        case = self._case(case_id)

        def related(collection: str, field: str = "case_id") -> list[dict[str, Any]]:
            return [item for item in self.store.list(collection) if item.get(field) == case_id]

        bundle = {
            "case": case,
            "signal": self.store.get("signals", case["signal_id"]),
            "acceptance_spec": self.store.get("acceptance_specs", case["acceptance_spec_id"])
            if case.get("acceptance_spec_id")
            else None,
            "acceptance_draft": self.store.get("acceptance_drafts", case["acceptance_draft_id"])
            if case.get("acceptance_draft_id")
            else None,
            "version_snapshot": self.store.get("version_snapshots", case["version_snapshot_id"])
            if case.get("version_snapshot_id")
            else None,
            "episode_snapshot": self.store.get("episode_snapshots", case["episode_snapshot_id"])
            if case.get("episode_snapshot_id")
            else None,
            "evidence": related("evidence"),
            "investigations": related("investigations"),
            "candidates": related("candidates"),
            "gate_reports": related("gate_reports"),
            "verified_candidates": related("verified_candidates"),
            "release_plans": related("release_plans"),
            "work_orders": related("work_orders"),
            "approvals": related("approvals"),
            "operations": related("operations"),
            "regression_assets": related("regression_assets"),
            "audit": related("audit", "subject") + [
                item for item in self.store.list("audit") if item.get("payload", {}).get("case_id") == case_id
            ],
        }
        bundle["digest"] = digest({"case": case, "gate": bundle["gate_reports"]})
        return bundle


def _normalize_component(item: dict[str, Any]) -> dict[str, Any]:
    assurance = str(item.get("assurance") or "UNKNOWN")
    if assurance not in ASSURANCE_VALUES:
        assurance = "UNKNOWN"
    row = {
        "kind": str(item.get("kind") or "unknown"),
        "ref": str(item.get("ref") or ""),
        "assurance": assurance,
    }
    if item.get("digest"):
        row["digest"] = item["digest"]
    return row


def _normalize_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(manifest)
    components = [_normalize_component(item) for item in (manifest.get("components") or []) if isinstance(item, dict)]
    if not components:
        if manifest.get("commit"):
            components.append(
                {
                    "kind": "upstream_commit",
                    "ref": str(manifest["commit"]),
                    "digest": str(manifest["commit"]),
                    "assurance": "PROVIDER_VERSION",
                }
            )
        if manifest.get("slug"):
            components.append(
                {
                    "kind": "workload",
                    "ref": str(manifest["slug"]),
                    "assurance": "OBSERVED_ONLY",
                }
            )
        components.append({"kind": "model", "ref": "unspecified", "assurance": "UNKNOWN"})
    normalized["components"] = components
    return normalized


def _next(
    code: str,
    principal: str,
    action: str,
    reason: str,
    *,
    missing: list[str] | None = None,
    skill: str = "",
    role: str = "",
) -> dict[str, Any]:
    return {
        "code": code,
        "principal": principal,
        "action": action,
        "reason": reason,
        "missing": list(missing or []),
        "skill": skill,
        "role": role,
    }


def _expired(expires_at: str | None) -> bool:
    if not expires_at:
        return False
    try:
        stamp = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
    except ValueError:
        return False
    return stamp <= datetime.now(timezone.utc)
