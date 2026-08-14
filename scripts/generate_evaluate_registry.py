"""Generate the 小智客服 exact-versionset evaluate registry.

The governed app (xiaozhi-customer-service) serves the CaseLoop 5-cell B1
attribution experiment through POST /v2/versionsets/{id}/evaluate.  This
script composes the immutable registry from the workload assets
(workloads/xiaozhi-customer-service/{prompts,kb.yaml}) and the frozen
component identities recorded by the CaseLoop control plane.

Frozen identities (control-plane record digests of component revisions):
  P0 = sha256:258a...  APPLICATION_CODE revision  agent-station-code (baseline)
  P1 = sha256:4dd5...  challenger prompt identity (B1 regression, v1.4.3)
  K0 = K1 = sha256:258a...  KB manifest (unchanged)
  M0 = M1 = sha256:4dd5...  model binding step-3.7-flash (unchanged)

Behavioral ground truth (B1): P0 cells (RP/G) recover the return-policy probes;
P1 cells (C/RK/RM) fail them.  The judge verifies behavior, not digests.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKLOAD = REPO_ROOT / "workloads" / "xiaozhi-customer-service"

P0_DIGEST = "sha256:258a5e4f0d50fbb4728b82d63f45f45412589a992ca2f2bf553ab7466f0503c7"
P1_DIGEST = "sha256:4dd5481cc1db92293181c38125df39536809155e11ec43f3f002c1373ac45a67"
K0_DIGEST = P0_DIGEST
M1_DIGEST = P1_DIGEST

VSET_DIGESTS = {
    "vset_cell_C": "sha256:26f97c233b50ec8590584e60e14a712315fa2daaa811869c9e8a0a1a08738c39",
    "vset_cell_RP": "sha256:2ca80927e0984c4b69420034e5789c65e05b45987f2a3b206ff8c449ce21f9e7",
    "vset_cell_RK": "sha256:94ca13da0a20b72db488d542310504dbe29854fb76b88f674baffa8e072edb58",
    "vset_cell_RM": "sha256:4227e085cc805d0905fbbb0aab963d5702513b207e14d022ecd0d03e69d1f3f8",
    "vset_cell_G": "sha256:9a8d33c9c4378e557eb9203a1c827d37362f7a838892bf77fe96297e85982f1a",
}

# Control-plane frozen cell bindings (prompt/kb/model component identities).
CELL_BINDINGS = {
    "vset_cell_C": ("P1", "K0", "M1"),
    "vset_cell_RP": ("P0", "K0", "M1"),
    "vset_cell_RK": ("P1", "K0", "M1"),
    "vset_cell_RM": ("P1", "K0", "M1"),
    "vset_cell_G": ("P0", "K0", "M1"),
}


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    p0_text = (WORKLOAD / "prompts" / "system.v1.4.2.md").read_text(encoding="utf-8")
    p1_text = (WORKLOAD / "prompts" / "system.v1.4.3.b1.md").read_text(encoding="utf-8")
    kb_doc = yaml.safe_load((WORKLOAD / "kb.yaml").read_text(encoding="utf-8"))
    kb_entries = kb_doc.get("entries") or []
    components = {
        "P0": {
            "kind": "prompt",
            "digest": P0_DIGEST,
            "ref": "workloads/xiaozhi-customer-service/prompts/system.v1.4.2.md",
            "content": p0_text,
            "content_sha256": _sha256_hex(p0_text.encode("utf-8")),
        },
        "P1": {
            "kind": "prompt",
            "digest": P1_DIGEST,
            "ref": "workloads/xiaozhi-customer-service/prompts/system.v1.4.3.b1.md",
            "content": p1_text,
            "content_sha256": _sha256_hex(p1_text.encode("utf-8")),
        },
        "K0": {
            "kind": "kb_manifest",
            "digest": K0_DIGEST,
            "ref": "workloads/xiaozhi-customer-service/kb.yaml",
            "entries": kb_entries,
        },
        "M1": {
            "kind": "model",
            "digest": M1_DIGEST,
            "model": "step-3.7-flash",
            "params": {"temperature": 0.0, "max_tokens": 1024},
        },
    }
    versionset_records = {}
    for vset_id, (prompt_key, kb_key, model_key) in CELL_BINDINGS.items():
        versionset_records[vset_id] = {
            "versionset_id": vset_id,
            "digest": VSET_DIGESTS[vset_id],
            "revision": 1,
            "content": {
                "prompt": {"digest": components[prompt_key]["digest"], "version": "v1.4.2" if prompt_key == "P0" else "v1.4.3"},
                "kb_manifest": {"digest": components[kb_key]["digest"], "version": "1.0.0"},
                "model": {"digest": components[model_key]["digest"], "model": components[model_key]["model"], "params": components[model_key]["params"]},
            },
        }
    registry = {
        "registry_id": "xiaozhi-customer-service-v1",
        "schema_version": "1.0",
        "frozen_by": "case-loop-b1-attribution",
        "identity_note": (
            "component digests are CaseLoop control-plane component-revision record "
            "digests (identities), bound to runtime content by this registry; "
            "behavioral correctness is verified by the deterministic probe judge."
        ),
        "cells": {vset: list(binding) for vset, binding in CELL_BINDINGS.items()},
        "components": components,
        "versionset_records": versionset_records,
    }
    out = WORKLOAD / "registry.json"
    out.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", out, f"({len(components)} components, {len(CELL_BINDINGS)} cells, {len(kb_entries)} kb entries)")


if __name__ == "__main__":
    main()
