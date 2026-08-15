from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from agentmed.config import Settings
from agentmed.kernel import Kernel
from agentmed.live import LiveStackError
from agentmed.review import case_manifest
from agentmed.store import Store


def _kernel(settings: Settings) -> str:
    return f"http://127.0.0.1:{settings.kernel_api_port}"


def _created_ts(case: dict[str, Any]) -> float:
    raw = str(case.get("created_at") or "")
    if not raw:
        return 0.0
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def wait_for_case(
    settings: Settings,
    *,
    signal_url: str,
    accept: bool,
    timeout_s: int,
    since_ts: float | None = None,
    accept_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = _kernel(settings)
    started = since_ts if since_ts is not None else time.time()
    deadline = time.time() + timeout_s
    accepted = False
    last: dict[str, Any] = {}
    last_state = ""
    with httpx.Client(timeout=15.0) as client:
        while time.time() < deadline:
            try:
                listed = client.get(f"{base}/v1/cases", params={"source_ref": signal_url}).json()
                cases = listed.get("cases") or []
                if cases:
                    case_id = cases[0]["id"]
                    bundle = client.get(f"{base}/v1/cases/{case_id}/evidence").json()
                    case = bundle.get("case") or {}
                    created = _created_ts(case)
                    if created and created < started - 2:
                        time.sleep(5)
                        continue
                    last = bundle
                    state = case.get("state")
                    if state and state != last_state:
                        print(f"kernel_state={state} case_id={case_id}", flush=True)
                        last_state = state
                    if accept and accept_body and not accepted and state == "awaiting_acceptance":
                        client.post(
                            f"{base}/v1/cases/{case_id}/accept",
                            headers={"X-AgentMED-Principal": "human:cli"},
                            json=accept_body,
                        ).raise_for_status()
                        accepted = True
                        time.sleep(1)
                        continue
                    if state == "closed":
                        kernel = Kernel(Store(settings.database_url, Path(settings.agentmed_data_dir)))
                        manifest = case_manifest(kernel, case_id, data_dir=Path(settings.agentmed_data_dir))
                        shown = dict(manifest)
                        shown.pop("patch_text", None)
                        bundle["manifest"] = shown
                        export_dir = Path(settings.agentmed_data_dir) / "exports"
                        export_dir.mkdir(parents=True, exist_ok=True)
                        path = export_dir / f"{case_id}.json"
                        path.write_text(json.dumps(bundle, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
                        bundle["export_path"] = str(path)
                        return bundle
            except Exception as exc:
                print(f"kernel_poll_error={type(exc).__name__}", flush=True)
            time.sleep(5)
    raise LiveStackError(
        "AgentTeams did not finish the Kernel case before timeout. "
        f"last_state={(last.get('case') or {}).get('state')}"
    )
