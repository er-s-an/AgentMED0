from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentmed.gate import base_source, golden_source, known_bad_source
from agentmed.kernel import ROLE_PRINCIPALS, Kernel
from agentmed.release import verify_candidate, write_draft_patch
from tests.conftest import KOTAEMON_ACCEPT
from tests.helpers import authorize_local_shadow
from agentmed.store import Store
from agentmed.workloads import (
    UnknownWorkload,
    get_adapter,
    list_adapters,
    register_adapter,
    unregister_adapter,
)
from agentmed.workloads.base import WorkloadSpec, run_pytest_eval


def make_kernel(tmp_path: Path) -> Kernel:
    db = tmp_path / "agentmed.db"
    store = Store(f"sqlite:///{db}", tmp_path / "data")
    return Kernel(store)


def make_toy_adapter(eval_dir: Path):
    eval_dir.mkdir(parents=True, exist_ok=True)
    (eval_dir / "test_add.py").write_text(
        "from add import add\n\n\ndef test_one_plus_one() -> None:\n    assert add(1, 1) == 2\n",
        encoding="utf-8",
    )

    class ToyAddAdapter:
        spec = WorkloadSpec(
            slug="toy-add",
            name="toy add",
            repo="https://example.invalid/toy-add",
            commit="deadbeef",
            path="tests/toy-add",
            allowed_files=("add.py",),
            default_expected="add(1, 1) == 2",
            default_badcase="add(1, 1)",
            default_judge="eval/test_add.py",
            attribute_hypothesis="add returns a + b + 1",
            builder_instruction="Return add.py so add(1, 1) == 2. POST files, not lightrag_store.py.",
        )

        def base_files(self) -> dict[str, str]:
            return {"add.py": "def add(a, b):\n    return a + b + 1\n"}

        def golden_files(self) -> dict[str, str]:
            return {"add.py": "def add(a, b):\n    return a + b\n"}

        def known_bad_files(self) -> dict[str, str]:
            return {"add.py": "def add(a, b):\n    return 0\n"}

        def run_eval(self, files: dict[str, str]) -> dict:
            return run_pytest_eval(eval_dir, {**self.base_files(), **files})

        def snapshot_manifest(self, issue: str | None = None) -> dict:
            manifest = {
                "repository": self.spec.repo,
                "commit": self.spec.commit,
                "slug": self.spec.slug,
                "allowed_files": list(self.spec.allowed_files),
            }
            if issue:
                manifest["issue"] = issue
            return manifest

    return ToyAddAdapter()


@pytest.fixture
def toy_adapter(tmp_path: Path):
    adapter = make_toy_adapter(tmp_path / "toy-eval")
    register_adapter(adapter)
    try:
        yield adapter
    finally:
        unregister_adapter(adapter.spec.slug)


def seed_case(kernel: Kernel, *, slug: str = "kotaemon", source_ref: str = "kotaemon#758") -> dict:
    app = kernel.ensure_app(slug, slug, "local")
    signal = kernel.ingest_signal(
        principal=ROLE_PRINCIPALS["intake"],
        source_type="issue",
        source_ref=source_ref,
        title="bad outcome",
        body="repro",
        application_id=app["id"],
        raw={},
    )
    case = kernel.open_case(
        principal=ROLE_PRINCIPALS["lead"],
        signal=signal,
        application=app,
    )
    kernel.confirm_acceptance(
        principal=ROLE_PRINCIPALS["human"],
        case_id=case["id"],
        expected_behavior="fixed",
        badcase_input="repro",
        judge="eval",
    )
    kernel.bind_version_snapshot(
        principal=ROLE_PRINCIPALS["investigator"],
        case_id=case["id"],
        manifest={"slug": slug},
    )
    kernel.seal_episode(principal=ROLE_PRINCIPALS["investigator"], case_id=case["id"], coverage={"test": True})
    kernel.add_investigation(
        principal=ROLE_PRINCIPALS["attribution"],
        case_id=case["id"],
        hypothesis="root cause",
        conclusion="SUPPORTED",
        uncertainty="test",
    )
    return kernel.store.get("cases", case["id"])


def test_kotaemon_base_fails_golden_passes_known_bad_fails() -> None:
    adapter = get_adapter("kotaemon")
    assert adapter.run_eval(adapter.base_files())["passed"] is False
    assert adapter.run_eval(adapter.golden_files())["passed"] is True
    assert adapter.run_eval(adapter.known_bad_files())["passed"] is False
    assert adapter.run_eval({"lightrag_store.py": base_source()})["passed"] is False
    assert adapter.run_eval({"lightrag_store.py": golden_source()})["passed"] is True
    assert adapter.run_eval({"lightrag_store.py": known_bad_source()})["passed"] is False


def test_unknown_slug_does_not_fall_back_to_kotaemon() -> None:
    with pytest.raises(UnknownWorkload, match="ghost"):
        get_adapter("ghost")


def test_toy_adapter_eval_is_independent_of_lightrag(toy_adapter, tmp_path: Path) -> None:
    assert toy_adapter.run_eval(toy_adapter.base_files())["passed"] is False
    assert toy_adapter.run_eval(toy_adapter.golden_files())["passed"] is True
    assert toy_adapter.run_eval(toy_adapter.known_bad_files())["passed"] is False
    kernel = make_kernel(tmp_path)
    case = seed_case(kernel, slug="toy-add", source_ref="toy#1")
    candidate = kernel.submit_candidate(
        principal=ROLE_PRINCIPALS["builder"],
        case_id=case["id"],
        summary="fix add",
        diff="",
        files=toy_adapter.golden_files(),
        risk="low",
    )
    assert "lightrag_store.py" not in candidate["files"]
    assert "add.py" in candidate["files"]
    report = verify_candidate(kernel, case["id"], candidate)
    assert report["verdict"] == "VERIFIED"
    assert report["evidence"]["workload"] == "toy-add"


def test_submit_without_diff_writes_unified_draft(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'agentmed.db'}")
    monkeypatch.setenv("AGENTMED_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REQUIRE_LIVE", "false")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")
    from agentmed.api import app

    client = TestClient(app)
    kernel = make_kernel(tmp_path)
    case = seed_case(kernel)
    submitted = client.post(
        f"/v1/cases/{case['id']}/candidates",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["builder"]},
        json={"summary": "scope by file_id", "files": {"lightrag_store.py": golden_source()}},
    )
    assert submitted.status_code == 200, submitted.text
    payload = submitted.json()
    assert "---" in payload["diff"] and "+++" in payload["diff"]
    assert "lightrag_store.py" in payload["diff"]
    updated = kernel.store.get("cases", case["id"])
    assert updated["candidate_id"] == payload["id"]
    assert payload["id"] in updated["candidate_ids"]
    drafted = write_draft_patch(kernel, case["id"], payload, tmp_path / "runtime")
    patch_text = Path(drafted["patch"]).read_text(encoding="utf-8")
    assert "---" in patch_text and "+++" in patch_text


def test_closed_asset_appears_in_next_gate_evidence(tmp_path: Path) -> None:
    kernel = make_kernel(tmp_path)
    first = seed_case(kernel, source_ref="kotaemon#758")
    first_candidate = kernel.submit_candidate(
        principal=ROLE_PRINCIPALS["builder"],
        case_id=first["id"],
        summary="first",
        diff="",
        files={"lightrag_store.py": golden_source()},
        risk="low",
    )
    verify_candidate(kernel, first["id"], first_candidate)
    asset = kernel.close_with_asset(
        principal=ROLE_PRINCIPALS["curator"],
        case_id=first["id"],
        summary="scoped retrieval",
        probes=["eval/test_file_scope.py"],
        lessons="persist file_id",
    )
    second = seed_case(kernel, source_ref="kotaemon#759")
    second_candidate = kernel.submit_candidate(
        principal=ROLE_PRINCIPALS["builder"],
        case_id=second["id"],
        summary="second",
        diff="",
        files={"lightrag_store.py": golden_source()},
        risk="low",
    )
    report = verify_candidate(kernel, second["id"], second_candidate)
    assert report["verdict"] == "VERIFIED"
    prior = report["evidence"]["prior_regression_assets"]
    assert any(item["id"] == asset["id"] for item in prior)
    assert any(item["probes"] == ["eval/test_file_scope.py"] for item in prior)
    assert any(item.get("ran") and item["ran"][0]["passed"] is True for item in prior)


def test_reject_keeps_candidate_ids_history(tmp_path: Path) -> None:
    kernel = make_kernel(tmp_path)
    case = seed_case(kernel)
    first = kernel.submit_candidate(
        principal=ROLE_PRINCIPALS["builder"],
        case_id=case["id"],
        summary="bad",
        diff="",
        files={"lightrag_store.py": base_source()},
        risk="high",
    )
    verify_candidate(kernel, case["id"], first)
    assert kernel.next_actions(case["id"])[0]["role"] == "builder"
    second = kernel.submit_candidate(
        principal=ROLE_PRINCIPALS["builder"],
        case_id=case["id"],
        summary="good",
        diff="",
        files={"lightrag_store.py": golden_source()},
        risk="low",
    )
    updated = kernel.store.get("cases", case["id"])
    assert updated["candidate_id"] == second["id"]
    assert updated["candidate_ids"] == [first["id"], second["id"]]


def test_next_points_at_the_legal_principal(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'agentmed.db'}")
    monkeypatch.setenv("AGENTMED_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REQUIRE_LIVE", "false")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")
    issue = {
        "url": "https://github.com/Cinnamon/kotaemon/issues/758",
        "title": "[BUG] LightRAG the qa is not scoped",
        "body": "selecting file A returns file B",
        "number": 758,
    }
    monkeypatch.setattr("agentmed.api.fetch_github_issue", lambda url, token="": issue)
    from agentmed.api import app

    client = TestClient(app)

    def next_role(case_id: str) -> str:
        payload = client.get(f"/v1/cases/{case_id}/next")
        assert payload.status_code == 200, payload.text
        actions = payload.json()["next"]
        return actions[0]["role"] if actions else ""

    ingested = client.post(
        "/v1/signals/ingest",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["intake"]},
        json={"url": issue["url"]},
    )
    assert ingested.status_code == 200, ingested.text
    case_id = ingested.json()["case"]["id"]
    assert next_role(case_id) == "human"
    client.post(f"/v1/cases/{case_id}/accept", headers={"X-AgentMED-Principal": "human:cli"}, json=KOTAEMON_ACCEPT)
    assert next_role(case_id) == "investigator"
    client.post(
        f"/v1/cases/{case_id}/investigate",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["investigator"]},
    )
    assert next_role(case_id) == "attribution"
    client.post(
        f"/v1/cases/{case_id}/attribute",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["attribution"]},
        json={},
    )
    assert next_role(case_id) == "builder"
    client.post(
        f"/v1/cases/{case_id}/candidates",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["builder"]},
        json={"summary": "scope by file_id", "lightrag_store_py": golden_source()},
    )
    assert next_role(case_id) == "verifier"
    verified = client.post(
        f"/v1/cases/{case_id}/verify",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["verifier"]},
    )
    assert verified.json()["verdict"] == "VERIFIED"
    assert next_role(case_id) == "lead"
    refused = client.post(
        f"/v1/cases/{case_id}/release",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["lead"]},
    )
    assert refused.status_code == 409
    authorize_local_shadow(client, case_id)
    assert next_role(case_id) == "lead"
    client.post(
        f"/v1/cases/{case_id}/release",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["lead"]},
    )
    assert next_role(case_id) == "curator"
    client.post(
        f"/v1/cases/{case_id}/close",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["curator"]},
        json={"summary": "scoped retrieval"},
    )
    empty = client.get(f"/v1/cases/{case_id}/next")
    assert empty.json()["next"] == []


def test_workloads_lists_registered_specs(toy_adapter, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'agentmed.db'}")
    monkeypatch.setenv("AGENTMED_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REQUIRE_LIVE", "false")
    from agentmed.api import app

    client = TestClient(app)
    listed = client.get("/v1/workloads")
    assert listed.status_code == 200, listed.text
    slugs = {item["slug"] for item in listed.json()["workloads"]}
    assert "kotaemon" in slugs
    assert "toy-add" in slugs
    assert any(spec.slug == "toy-add" for spec in list_adapters())


def test_extra_files_are_rejected(toy_adapter, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'agentmed.db'}")
    monkeypatch.setenv("AGENTMED_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REQUIRE_LIVE", "false")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")
    from agentmed.api import app

    client = TestClient(app)
    kernel = make_kernel(tmp_path)
    case = seed_case(kernel, slug="toy-add", source_ref="toy#2")
    refused = client.post(
        f"/v1/cases/{case['id']}/candidates",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["builder"]},
        json={
            "summary": "too many files",
            "files": {"add.py": toy_adapter.golden_files()["add.py"], "evil.py": "x = 1\n"},
        },
    )
    assert refused.status_code == 400, refused.text
    assert "not allowed" in refused.text


def test_unknown_application_slug_fails_builder_context(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'agentmed.db'}")
    monkeypatch.setenv("AGENTMED_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REQUIRE_LIVE", "false")
    from agentmed.api import app

    client = TestClient(app)
    kernel = make_kernel(tmp_path)
    case = seed_case(kernel, slug="ghost-app", source_ref="ghost#1")
    context = client.get(
        f"/v1/cases/{case['id']}/builder-context",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["builder"]},
    )
    assert context.status_code == 400, context.text
    assert "unknown workload" in context.text


def test_unmapped_github_repo_requires_slug(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'agentmed.db'}")
    monkeypatch.setenv("AGENTMED_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REQUIRE_LIVE", "false")
    monkeypatch.setattr(
        "agentmed.api.fetch_github_issue",
        lambda url, token="": {"url": url, "title": "openclaw bug", "body": "x", "number": 1},
    )
    from agentmed.api import app

    client = TestClient(app)
    refused = client.post(
        "/v1/signals/ingest",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["intake"]},
        json={"url": "https://github.com/openclaw/openclaw/issues/84572"},
    )
    assert refused.status_code == 400, refused.text
    assert "unknown workload" in refused.text


def test_review_page_and_manifest_after_full_loop(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'agentmed.db'}")
    monkeypatch.setenv("AGENTMED_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REQUIRE_LIVE", "false")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")
    issue = {
        "url": "https://github.com/Cinnamon/kotaemon/issues/758",
        "title": "[BUG] LightRAG the qa is not scoped",
        "body": "selecting file A returns file B",
        "number": 758,
    }
    monkeypatch.setattr("agentmed.api.fetch_github_issue", lambda url, token="": issue)
    from agentmed.api import app

    client = TestClient(app)
    page = client.get("/")
    assert page.status_code == 200
    assert "VerifiedCandidate" in page.text
    ingested = client.post(
        "/v1/signals/ingest",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["intake"]},
        json={"url": issue["url"]},
    )
    case_id = ingested.json()["case"]["id"]
    client.post(f"/v1/cases/{case_id}/accept", headers={"X-AgentMED-Principal": "human:cli"}, json=KOTAEMON_ACCEPT)
    client.post(
        f"/v1/cases/{case_id}/investigate",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["investigator"]},
    )
    client.post(
        f"/v1/cases/{case_id}/attribute",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["attribution"]},
        json={},
    )
    client.post(
        f"/v1/cases/{case_id}/candidates",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["builder"]},
        json={"summary": "scope by file_id", "lightrag_store_py": golden_source()},
    )
    verified = client.post(
        f"/v1/cases/{case_id}/verify",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["verifier"]},
    )
    assert verified.json()["verdict"] == "VERIFIED"
    authorize_local_shadow(client, case_id)
    client.post(f"/v1/cases/{case_id}/release", headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["lead"]})
    client.post(
        f"/v1/cases/{case_id}/close",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["curator"]},
        json={"summary": "scoped retrieval"},
    )
    review = client.get(f"/v1/cases/{case_id}/review")
    assert review.status_code == 200, review.text
    manifest = review.json()["manifest"]
    assert manifest["workload"] == "kotaemon"
    assert manifest["gate_verdict"] == "VERIFIED"
    assert manifest["verified_status"] == "NOT_DEPLOYED"
    assert manifest["unauthorized_external"] == 0
    assert manifest["next"] == []
    assert manifest["draft_patch"]
    assert "---" in (manifest.get("patch_text") or "")
    assert "+++" in (manifest.get("patch_text") or "")
