from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import typer
from dotenv import load_dotenv

from agentmed.config import load_settings
from agentmed.kernel import Kernel
from agentmed.live import LiveStackError, as_report, probe_all
from agentmed.server import ensure_kernel
from agentmed.store import Store
from agentmed.prpack import HumanRequired, PackNotReady, build_pr_pack, submit_upstream_pr
from agentmed.review import case_manifest
from agentmed.team.agentteams import apply_pack, ensure_pack
from agentmed.team.dispatch import dispatch_loop
from agentmed.team.runtime import wait_for_case

load_dotenv()

app = typer.Typer(name="agentmed", help="AgentMED quality loop CLI")
case_app = typer.Typer(help="Inspect cases")
evidence_app = typer.Typer(help="Export case evidence")
pr_app = typer.Typer(help="Human-reviewable upstream PR pack")
app.add_typer(case_app, name="case")
app.add_typer(evidence_app, name="evidence")
app.add_typer(pr_app, name="pr")


def _kernel() -> tuple[Kernel, Path]:
    settings = load_settings()
    data_dir = Path(settings.agentmed_data_dir)
    store = Store(settings.database_url, data_dir)
    return Kernel(store), data_dir


def _write_export(bundle: dict, data_dir: Path, case_id: str) -> Path:
    export_dir = data_dir / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    path = export_dir / f"{case_id}.json"
    path.write_text(json.dumps(bundle, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path


@app.command()
def doctor() -> None:
    """Check that AgentTeams, Langfuse, Step Plan, Gate, and GitHub intake are live."""
    settings = load_settings()
    report = as_report(probe_all(settings))
    for probe in report["probes"]:
        flag = "OK" if probe["ok"] else "FAIL"
        typer.echo(f"{flag:4} {probe['name']:11} {probe['detail']}")
    if not report["ok"]:
        raise typer.Exit(code=1)


@app.command()
def serve(
    host: str = typer.Option(None, "--host"),
    port: int = typer.Option(None, "--port"),
) -> None:
    """Run the Kernel HTTP API as a real process."""
    import uvicorn

    settings = load_settings()
    uvicorn.run(
        "agentmed.api:app",
        host=host or settings.kernel_listen_host,
        port=port or settings.kernel_api_port,
        reload=False,
    )


@app.command()
def apply_agentteams() -> None:
    """Apply AgentMED workers/team/skills onto a running AgentTeams cluster."""
    try:
        result = apply_pack(load_settings())
    except LiveStackError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(result, indent=2, ensure_ascii=False))


@app.command()
def run(
    signal: str = typer.Option(..., "--signal", help="GitHub issue URL"),
    accept: bool = typer.Option(False, "--accept/--no-accept", help="Confirm AcceptanceSpec after Case opens"),
    accept_adapter_defaults: bool = typer.Option(
        False,
        "--accept-adapter-defaults",
        help="Auditable shortcut: confirm the adapter draft. Not a silent default.",
    ),
    expected: str = typer.Option("", "--expected", help="Human-confirmed expected behavior"),
    badcase: str = typer.Option("", "--badcase", help="Human-confirmed bad-case input"),
    judge: str = typer.Option("", "--judge", help="How the Gate should judge"),
    timeout: int = typer.Option(1200, "--timeout", help="Seconds to wait for AgentTeams to finish"),
) -> None:
    """Dispatch a quality loop to AgentTeams and wait on Kernel state."""
    settings = load_settings()
    from agentmed.live import assert_live

    accept_body: dict[str, Any] | None = None
    if accept_adapter_defaults:
        accept_body = {"confirm_adapter_defaults": True}
    elif accept:
        if not expected.strip() or not badcase.strip():
            typer.echo(
                "NEEDS_ACCEPTANCE_CRITERIA: pass --expected and --badcase, "
                "or --accept-adapter-defaults if you are confirming the adapter draft.",
                err=True,
            )
            raise typer.Exit(code=2)
        accept_body = {
            "expected_behavior": expected,
            "badcase_input": badcase,
            "judge": judge,
        }
    try:
        live = assert_live(settings, signal_url=signal)
        kernel_info = ensure_kernel(settings)
        if os.environ.get("AGENTMED_SKIP_SKILL_SYNC") != "1":
            typer.echo("syncing AgentMED skills onto AgentTeams workers…")
            applied = ensure_pack(settings)
            typer.echo((applied.get("workers") or applied.get("status") or "synced"))
        dispatched = dispatch_loop(settings, signal_url=signal, accept=bool(accept_body))
        typer.echo(f"kernel={kernel_info['url']} status={kernel_info['status']}")
        typer.echo(f"dispatched_event={dispatched['dispatch'].get('event_id')}")
        bundle = wait_for_case(
            settings,
            signal_url=signal,
            accept=bool(accept_body),
            accept_body=accept_body,
            timeout_s=timeout,
        )
    except LiveStackError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    case = bundle.get("case") or {}
    reports = bundle.get("gate_reports") or []
    verdict = reports[-1]["verdict"] if reports else None
    export_path = bundle.get("export_path", "")
    typer.echo(f"case_id={case.get('id')}")
    typer.echo(f"state={case.get('state')}")
    typer.echo(f"gate_verdict={verdict}")
    typer.echo(f"verified_status={(bundle.get('verified_candidates') or [{}])[-1].get('status')}")
    typer.echo(f"executor=agentteams")
    typer.echo(f"live_ok={live.get('ok')}")
    typer.echo(f"export_path={export_path}")


@case_app.command("list")
def case_list() -> None:
    kernel, _ = _kernel()
    typer.echo(json.dumps({"cases": kernel.list_cases()}, indent=2, ensure_ascii=False, default=str))


@case_app.command("show")
def case_show(case_id: str) -> None:
    kernel, _ = _kernel()
    bundle = kernel.export_case(case_id)
    typer.echo(json.dumps(bundle, indent=2, ensure_ascii=False, default=str))


@case_app.command("next")
def case_next(case_id: str) -> None:
    kernel, _ = _kernel()
    case = kernel._case(case_id)
    typer.echo(
        json.dumps(
            {"case_id": case_id, "state": case.get("state"), "next": kernel.next_actions(case_id)},
            indent=2,
            ensure_ascii=False,
        )
    )


@evidence_app.command("export")
def evidence_export(case_id: str) -> None:
    kernel, data_dir = _kernel()
    bundle = kernel.export_case(case_id)
    manifest = case_manifest(kernel, case_id, data_dir=data_dir)
    shown = dict(manifest)
    shown.pop("patch_text", None)
    bundle["manifest"] = shown
    path = _write_export(bundle, data_dir, case_id)
    typer.echo(f"case_id={manifest['case_id']}")
    typer.echo(f"state={manifest['state']}")
    typer.echo(f"workload={manifest['workload']}")
    typer.echo(f"gate_verdict={manifest['gate_verdict']}")
    typer.echo(f"verified_status={manifest['verified_status']}")
    typer.echo(f"draft_patch={manifest['draft_patch']}")
    typer.echo(f"unauthorized_external={manifest['unauthorized_external']}")
    typer.echo(f"pr_pack={manifest.get('pr_pack') or ''}")
    typer.echo(str(path))


@pr_app.command("pack")
def pr_pack(case_id: str) -> None:
    """Write a human-reviewable upstream PR pack. Does not open a PR."""
    kernel, data_dir = _kernel()
    packed = build_pr_pack(kernel, case_id, data_dir=data_dir)
    shown = packed["manifest"]
    typer.echo(f"case_id={shown['case_id']}")
    typer.echo(f"ready_to_submit={shown['ready_to_submit']}")
    typer.echo(f"upstream_issue={shown['upstream_issue']}")
    typer.echo(f"pack_dir={shown['pack_dir']}")
    typer.echo(shown["dry_run_command"])
    typer.echo(shown["submit_command"])


@pr_app.command("submit")
def pr_submit(
    case_id: str,
    i_am_human: bool = typer.Option(False, "--i-am-human", help="Required. AgentMED will not open a PR otherwise."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print gh/git steps only."),
    repo_dir: Path | None = typer.Option(None, "--repo-dir", help="kotaemon checkout for an actual submit."),
) -> None:
    """Open the upstream PR. Refuses unless a human passes --i-am-human."""
    kernel, data_dir = _kernel()
    packed = build_pr_pack(kernel, case_id, data_dir=data_dir)
    try:
        result = submit_upstream_pr(
            Path(packed["pack_dir"]),
            i_am_human=i_am_human,
            dry_run=dry_run,
            repo_dir=repo_dir,
        )
    except HumanRequired as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    except PackNotReady as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(result, indent=2, ensure_ascii=False))


@app.command("mcp")
def mcp_stdio() -> None:
    """Start the stdio MCP gateway. Does not expose approvals or execute."""
    from agentmed.mcp_server import serve_stdio

    serve_stdio()


@app.command("init")
def init_repo(
    repo: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True, readable=True),
    import_manifest: bool = typer.Option(False, "--import", help="Write the draft into applications. Requires human:"),
    principal: str = typer.Option("human:cli", "--principal"),
    out: Path | None = typer.Option(None, "--out", help="Where to write system-manifest.draft.json"),
) -> None:
    """Scan a repo and write a draft system manifest. Unknown components stay UNKNOWN."""
    from agentmed.init_app import import_draft, write_draft

    path = write_draft(repo, dest=out)
    typer.echo(str(path))
    if not import_manifest:
        return
    if not principal.startswith("human:"):
        typer.echo("init --import requires a human: principal", err=True)
        raise typer.Exit(code=2)
    kernel, _ = _kernel()
    imported = import_draft(kernel, principal=principal, repo=repo)
    typer.echo(json.dumps({"application_id": imported["application"]["id"], "slug": imported["application"]["slug"]}))
