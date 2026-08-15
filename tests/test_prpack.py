from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentmed.gate import golden_source
from agentmed.kernel import ROLE_PRINCIPALS, Kernel
from agentmed.prpack import HumanRequired, PackNotReady, build_pr_pack, submit_upstream_pr
from agentmed.release import verify_candidate
from agentmed.store import Store
from agentmed.workloads.kotaemon_upstream import (
    UPSTREAM_PATH,
    apply_kotaemon_758,
    load_base,
    upstream_patch_text,
)


def make_kernel(tmp_path: Path) -> Kernel:
    db = tmp_path / "agentmed.db"
    store = Store(f"sqlite:///{db}", tmp_path / "data")
    return Kernel(store)


def seed_verified(kernel: Kernel) -> dict:
    app = kernel.ensure_app("kotaemon", "kotaemon", "https://github.com/Cinnamon/kotaemon")
    signal = kernel.ingest_signal(
        principal=ROLE_PRINCIPALS["intake"],
        source_type="issue",
        source_ref="https://github.com/Cinnamon/kotaemon/issues/758",
        title="LightRAG the qa is not scoped",
        body="selecting file A returns file B",
        application_id=app["id"],
        raw={},
    )
    case = kernel.open_case(principal=ROLE_PRINCIPALS["lead"], signal=signal, application=app)
    kernel.confirm_acceptance(
        principal=ROLE_PRINCIPALS["human"],
        case_id=case["id"],
        expected_behavior="selected file A must not retrieve file B",
        badcase_input="upload a.pdf and b.pdf; select only a.pdf",
        judge="eval",
    )
    kernel.bind_version_snapshot(
        principal=ROLE_PRINCIPALS["investigator"],
        case_id=case["id"],
        manifest={"slug": "kotaemon", "issue": "758"},
    )
    kernel.seal_episode(principal=ROLE_PRINCIPALS["investigator"], case_id=case["id"], coverage={"test": True})
    kernel.add_investigation(
        principal=ROLE_PRINCIPALS["attribution"],
        case_id=case["id"],
        hypothesis="file_id is dropped on insert/query",
        conclusion="SUPPORTED",
        uncertainty="test",
    )
    candidate = kernel.submit_candidate(
        principal=ROLE_PRINCIPALS["builder"],
        case_id=case["id"],
        summary="scope by file_id",
        diff="",
        files={"lightrag_store.py": golden_source()},
        risk="low",
    )
    report = verify_candidate(kernel, case["id"], candidate)
    assert report["verdict"] == "VERIFIED"
    return kernel.store.get("cases", case["id"])


def test_upstream_patch_applies_to_pinned_snapshot(tmp_path: Path) -> None:
    base = load_base()
    patched = apply_kotaemon_758(base)
    assert "insert_kwargs" in patched
    assert "Older LightRAG only accepted a single text blob." in patched
    assert "file_ids=self.file_ids" in patched
    assert "file_ids[0]" not in patched
    dest = tmp_path / UPSTREAM_PATH
    dest.parent.mkdir(parents=True)
    dest.write_text(base, encoding="utf-8")
    patch = tmp_path / "upstream.patch"
    patch.write_text(upstream_patch_text(), encoding="utf-8")
    import subprocess

    applied = subprocess.run(["git", "apply", str(patch)], cwd=tmp_path, capture_output=True, text=True)
    assert applied.returncode == 0, applied.stderr
    assert dest.read_text(encoding="utf-8") == patched


def test_pr_pack_is_reviewable_and_not_auto_submitted(tmp_path: Path) -> None:
    kernel = make_kernel(tmp_path)
    case = seed_verified(kernel)
    packed = build_pr_pack(kernel, case["id"], data_dir=tmp_path / "data")
    manifest = packed["manifest"]
    assert manifest["ready_to_submit"] is True
    assert manifest["auto_submit"] is False
    assert manifest["gate_verified"] == "upstream"
    assert "upstream" in manifest["gate_surfaces"]
    assert "harness" in manifest["gate_surfaces"]
    assert "758" in manifest["upstream_issue"]
    assert manifest["upstream_path"] == UPSTREAM_PATH
    pack_dir = Path(packed["pack_dir"])
    assert (pack_dir / "PR.md").read_text(encoding="utf-8").startswith("# fix(lightrag):")
    assert "Closes #758" not in (pack_dir / "PR.md").read_text(encoding="utf-8")
    assert "Related to #758" in (pack_dir / "PR.md").read_text(encoding="utf-8")
    assert "--- a/" + UPSTREAM_PATH in (pack_dir / "upstream.patch").read_text(encoding="utf-8")
    assert "lightrag_store.py" in (pack_dir / "harness.patch").read_text(encoding="utf-8")
    with pytest.raises(HumanRequired, match="--i-am-human"):
        submit_upstream_pr(pack_dir, i_am_human=False)
    dry = submit_upstream_pr(pack_dir, i_am_human=True, dry_run=True)
    assert dry["status"] == "dry_run"
    with pytest.raises(PackNotReady, match="repo-dir"):
        submit_upstream_pr(pack_dir, i_am_human=True, dry_run=False)


def test_review_api_exposes_pr_pack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'agentmed.db'}")
    monkeypatch.setenv("AGENTMED_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REQUIRE_LIVE", "false")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")
    kernel = make_kernel(tmp_path)
    case = seed_verified(kernel)
    from agentmed.api import app

    client = TestClient(app)
    page = client.get("/")
    assert "PR 包" in page.text
    assert "harness.patch" in page.text
    assert "upstream.patch" in page.text
    assert "不会开 PR" in page.text
    packed = client.get(f"/v1/cases/{case['id']}/pr-pack")
    assert packed.status_code == 200, packed.text
    body = packed.json()
    assert body["manifest"]["ready_to_submit"] is True
    assert "Closes #758" not in body["pr_md"]
    assert "insert_kwargs" in body["upstream_patch"]
    review = client.get(f"/v1/cases/{case['id']}/review")
    assert review.json()["manifest"]["pr_pack"]
    assert review.json()["manifest"]["upstream_issue"].endswith("/758")
