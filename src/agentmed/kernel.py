from __future__ import annotations

from typing import Any

from agentmed.ids import digest, new_id, utcnow
from agentmed.store import Store

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
    pass


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
            "gate_report_id": None,
            "verified_candidate_id": None,
            "regression_asset_id": None,
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

    def confirm_acceptance(
        self,
        *,
        principal: str,
        case_id: str,
        expected_behavior: str,
        badcase_input: str,
        judge: str,
    ) -> dict[str, Any]:
        if not principal.startswith("human:"):
            raise KernelError("AcceptanceSpec must be confirmed by a human principal")
        case = self._case(case_id)
        spec = {
            "id": new_id("spec"),
            "case_id": case_id,
            "expected_behavior": expected_behavior,
            "badcase_input": badcase_input,
            "judge": judge,
            "confirmed_by": principal,
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
        snapshot = {
            "id": new_id("ver"),
            "case_id": case_id,
            "manifest": manifest,
            "created_by": principal,
            "created_at": utcnow(),
        }
        snapshot["digest"] = digest(manifest)
        self.store.put("version_snapshots", snapshot)
        case["version_snapshot_id"] = snapshot["id"]
        self.store.put("cases", case)
        self.audit("version.bind", principal, snapshot["id"], {"digest": snapshot["digest"]})
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
    ) -> dict[str, Any]:
        if conclusion not in {"SUPPORTED", "REFUTED", "INCONCLUSIVE", "CONFOUNDED"}:
            raise KernelError("invalid investigation conclusion")
        report = {
            "id": new_id("inv"),
            "case_id": case_id,
            "hypothesis": hypothesis,
            "conclusion": conclusion,
            "uncertainty": uncertainty,
            "created_by": principal,
            "created_at": utcnow(),
        }
        self.store.put("investigations", report)
        self._set_state(self._case(case_id), "proposing", principal)
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
    ) -> dict[str, Any]:
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
            "version_snapshot": self.store.get("version_snapshots", case["version_snapshot_id"])
            if case.get("version_snapshot_id")
            else None,
            "evidence": related("evidence"),
            "investigations": related("investigations"),
            "candidates": related("candidates"),
            "gate_reports": related("gate_reports"),
            "verified_candidates": related("verified_candidates"),
            "operations": related("operations"),
            "regression_assets": related("regression_assets"),
            "audit": related("audit", "subject") + [
                item for item in self.store.list("audit") if item.get("payload", {}).get("case_id") == case_id
            ],
        }
        bundle["digest"] = digest({"case": case, "gate": bundle["gate_reports"]})
        return bundle
