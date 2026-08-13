from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import httpx

from agentmed.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]


def kernel_reachable(settings: Settings, timeout: float = 2.0) -> bool:
    url = f"http://127.0.0.1:{settings.kernel_api_port}/ready"
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(url)
        return response.status_code < 500
    except Exception:
        return False


def ensure_kernel(settings: Settings) -> dict:
    if kernel_reachable(settings):
        return {"status": "already-running", "url": f"http://127.0.0.1:{settings.kernel_api_port}"}
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "agentmed.api:app",
        "--host",
        settings.kernel_listen_host,
        "--port",
        str(settings.kernel_api_port),
    ]
    log_path = Path(settings.agentmed_data_dir) / "kernel-api.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("ab")
    subprocess.Popen(
        cmd,
        cwd=str(REPO_ROOT),
        stdout=handle,
        stderr=handle,
        start_new_session=True,
    )
    deadline = time.time() + 20
    while time.time() < deadline:
        if kernel_reachable(settings):
            return {"status": "started", "url": f"http://127.0.0.1:{settings.kernel_api_port}", "log": str(log_path)}
        time.sleep(0.4)
    raise RuntimeError(f"Kernel API did not start; see {log_path}")
