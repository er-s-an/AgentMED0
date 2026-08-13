from __future__ import annotations

import json
import os
from pathlib import Path

import typer
from dotenv import load_dotenv

from agentmed.config import load_settings
from agentmed.kernel import Kernel
from agentmed.live import LiveStackError, as_report, probe_all
from agentmed.server import ensure_kernel
from agentmed.store import Store
from agentmed.team.agentteams import apply_pack, ensure_pack
from agentmed.team.dispatch import dispatch_loop
from agentmed.team.runtime import wait_for_case

load_dotenv()

app = typer.Typer(name="agentmed", help="AgentMED quality loop CLI")
case_app = typer.Typer(help="Inspect cases")
evidence_app = typer.Typer(help="Export case evidence")
app.add_typer(case_app, name="case")
app.add_typer(evidence_app, name="evidence")


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
    accept: bool = typer.Option(True, "--accept/--no-accept", help="Confirm AcceptanceSpec"),
    timeout: int = typer.Option(1200, "--timeout", help="Seconds to wait for AgentTeams to finish"),
) -> None:
    """Dispatch a quality loop to AgentTeams and wait on Kernel state."""
    settings = load_settings()
    from agentmed.live import assert_live

    try:
        live = assert_live(settings, signal_url=signal)
        kernel_info = ensure_kernel(settings)
        if os.environ.get("AGENTMED_SKIP_SKILL_SYNC") != "1":
            typer.echo("syncing AgentMED skills onto AgentTeams workers…")
            applied = ensure_pack(settings)
            typer.echo((applied.get("workers") or applied.get("status") or "synced"))
        dispatched = dispatch_loop(settings, signal_url=signal, accept=accept)
        typer.echo(f"kernel={kernel_info['url']} status={kernel_info['status']}")
        typer.echo(f"dispatched_event={dispatched['dispatch'].get('event_id')}")
        bundle = wait_for_case(
            settings,
            signal_url=signal,
            accept=accept,
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


@case_app.command("show")
def case_show(case_id: str) -> None:
    kernel, _ = _kernel()
    bundle = kernel.export_case(case_id)
    typer.echo(json.dumps(bundle, indent=2, ensure_ascii=False, default=str))


@evidence_app.command("export")
def evidence_export(case_id: str) -> None:
    kernel, data_dir = _kernel()
    bundle = kernel.export_case(case_id)
    path = _write_export(bundle, data_dir, case_id)
    typer.echo(str(path))
