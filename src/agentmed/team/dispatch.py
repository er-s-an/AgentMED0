from __future__ import annotations

import json
import os
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Any

import httpx

from agentmed.config import Settings
from agentmed.live import LiveStackError

SOUL_MARK_START = "<!-- agentmed-start -->"
SOUL_MARK_END = "<!-- agentmed-end -->"
SOUL_APPENDIX = """
<!-- agentmed-start -->
# AgentMED (product loop)

You are the Manager of the AgentMED quality team. Kernel HTTP is source of truth.
Matrix chat is coordination only.

Kernel for Workers (Docker Desktop): http://host.docker.internal:8088

When the admin asks to run AgentMED on a GitHub issue:

1. Do not write application code yourself.
2. Ensure Team `agentmed-quality` Workers exist (`agt get workers`). If missing, `agt apply` the pack under `/tmp/agentmed-pack` or tell admin CLI already applied them.
3. Delegate to Team Leader `quality-officer` in the **Leader Room** via `copaw channels send`.
   Use the full Matrix ID `@quality-officer:matrix-local.agentteams.io:18080`.
   Do not @mention team Workers from admin DM — they cannot see it.
   Do not create new Workers; team `agentmed-quality` is already Running.
4. quality-officer must drive this order, each Worker calling Kernel with header `X-AgentMED-Principal`:
   - intake `agent:intake` → POST /v1/signals/ingest `{"url":"<issue>"}`
   - wait until Case state is `investigating` (human CLI confirms AcceptanceSpec)
   - investigator `agent:investigator` → POST /v1/cases/{id}/investigate
   - attribution `agent:attribution` → POST /v1/cases/{id}/attribute
   - builder `agent:builder` → GET /v1/cases/{id}/builder-context then POST /v1/cases/{id}/candidates
   - verifier `agent:verifier` → GET /v1/cases/{id}/verifier-context then POST /v1/cases/{id}/verify
   - on REJECT: builder retries from GateReport only; never patch a sealed candidate
   - on VERIFIED: quality-officer POST /v1/cases/{id}/release
   - curator `agent:curator` → POST /v1/cases/{id}/close
5. After every step, GET /v1/cases/{id} from Kernel. Do not trust Worker self-report.
6. YOLO: do not ask the admin to confirm Worker creation or task assignment.
7. Never merge, git push, or production-deploy.
8. A closed Case for kotaemon #758 from a previous local playbook (`[fallback-golden]`) does NOT count. Intake must POST /v1/signals/ingest anyway; Kernel will open a NEW Case because the old one is closed. Do not report the old Case as success.


kotaemon #758 is the first workload. Builder may only change lightrag_store.py.
<!-- agentmed-end -->
"""


def _env_file() -> Path:
    return Path.home() / "agentteams-manager.env"


def read_manager_env() -> dict[str, str]:
    path = _env_file()
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def rewrite_env_key(path: Path, key: str, value: str) -> dict[str, Any]:
    """Replace a single env assignment. Return status only — never other secret values."""
    if not path.exists():
        return {"status": "missing", "changed": False, "key": key, "path": str(path)}
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    found = False
    changed = False
    out: list[str] = []
    assignment = f"{key}={value}"
    for line in lines:
        if line.startswith(f"{key}="):
            found = True
            current = line.split("=", 1)[1].strip()
            newline = "\n" if line.endswith("\n") else ""
            if current != value:
                out.append(assignment + newline)
                changed = True
            else:
                out.append(line)
        else:
            out.append(line)
    if not found:
        suffix = "" if original.endswith("\n") or not original else "\n"
        out.append(f"{suffix}{assignment}\n")
        changed = True
    if changed:
        path.write_text("".join(out), encoding="utf-8")
    return {
        "status": "updated" if changed else "already",
        "changed": changed,
        "key": key,
        "url": value,
        "path": str(path),
    }


def retarget_agentteams_llm(settings: Settings) -> dict[str, Any]:
    """Point AgentTeams at the Kernel LLM proxy. Opt-in: AGENTMED_RETARGET_LLM=1.

    Does not print secrets. Does not rewrite the file unless explicitly enabled,
    so `apply-agentteams` on someone else's cluster is not a surprise.
    """
    url = f"http://host.docker.internal:{settings.kernel_api_port}/v1"
    if os.environ.get("AGENTMED_RETARGET_LLM") != "1":
        return {
            "status": "skipped",
            "changed": False,
            "key": "AGENTTEAMS_OPENAI_BASE_URL",
            "url": url,
            "note": "Set AGENTMED_RETARGET_LLM=1 to rewrite AGENTTEAMS_OPENAI_BASE_URL outside this repo.",
        }
    result = rewrite_env_key(_env_file(), "AGENTTEAMS_OPENAI_BASE_URL", url)
    result["restart_required"] = bool(result.get("changed"))
    result["note"] = (
        "Existing AgentTeams containers keep the old LLM URL until they are recreated. "
        "Kernel holds the model API key; workers call POST /v1/chat/completions on Kernel."
    )
    return result


def enable_yolo(settings: Settings) -> Path:
    marker = Path(settings.agentteams_workspace) / "yolo-mode"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("1\n", encoding="utf-8")
    os.environ["AGENTTEAMS_YOLO"] = "1"
    return marker


def patch_manager_soul(settings: Settings) -> Path:
    soul = Path(settings.agentteams_workspace) / "SOUL.md"
    text = soul.read_text(encoding="utf-8") if soul.exists() else ""
    if SOUL_MARK_START in text:
        start = text.index(SOUL_MARK_START)
        end = text.index(SOUL_MARK_END) + len(SOUL_MARK_END) if SOUL_MARK_END in text else len(text)
        text = text[:start].rstrip() + "\n" + SOUL_APPENDIX.strip() + "\n" + text[end:].lstrip("\n")
    else:
        text = text.rstrip() + "\n\n" + SOUL_APPENDIX.strip() + "\n"
    soul.write_text(text, encoding="utf-8")
    return soul


def manager_chat(settings: Settings) -> dict[str, Any]:
    url = "http://127.0.0.1:18888/api/chats"
    with httpx.Client(timeout=8.0) as client:
        response = client.get(url)
        response.raise_for_status()
        chats = response.json()
    if not chats:
        raise LiveStackError("QwenPaw has no Manager chats yet; wait for install welcome to finish")
    return chats[0]


def matrix_login(settings: Settings) -> str:
    env = read_manager_env()
    user = env.get("AGENTTEAMS_ADMIN_USER") or "admin"
    password = env.get("AGENTTEAMS_ADMIN_PASSWORD") or ""
    if not password:
        raise LiveStackError("AGENTTEAMS_ADMIN_PASSWORD missing in ~/agentteams-manager.env")
    gateway = settings.agentteams_gateway.rstrip("/")
    payload = {
        "type": "m.login.password",
        "identifier": {"type": "m.id.user", "user": user},
        "password": password,
        "initial_device_display_name": "agentmed-cli",
    }
    with httpx.Client(timeout=20.0) as client:
        response = client.post(f"{gateway}/_matrix/client/v3/login", json=payload)
        if response.status_code >= 400:
            raise LiveStackError(f"Matrix login failed HTTP {response.status_code}")
        token = response.json().get("access_token")
    if not token:
        raise LiveStackError("Matrix login returned no access_token")
    return token


def send_manager_message(settings: Settings, text: str) -> dict[str, Any]:
    chat = manager_chat(settings)
    session = str(chat.get("session_id") or "")
    if not session.startswith("matrix:"):
        raise LiveStackError(f"unexpected Manager session {session}")
    room_id = session[len("matrix:") :]
    token = matrix_login(settings)
    gateway = settings.agentteams_gateway.rstrip("/")
    txn = uuid.uuid4().hex
    encoded_room = urllib.parse.quote(room_id, safe="")
    url = f"{gateway}/_matrix/client/v3/rooms/{encoded_room}/send/m.room.message/{txn}"
    with httpx.Client(timeout=20.0) as client:
        response = client.put(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json={"msgtype": "m.text", "body": text},
        )
        if response.status_code >= 400:
            raise LiveStackError(f"Matrix send failed HTTP {response.status_code}: {response.text[:300]}")
        event = response.json()
    return {"room_id": room_id, "event_id": event.get("event_id"), "chat_id": chat.get("id")}


def wait_workers(timeout_s: int = 180) -> list[str]:
    from agentmed.team.agentteams import list_worker_names

    deadline = time.time() + timeout_s
    names: list[str] = []
    while time.time() < deadline:
        names = list_worker_names()
        if names:
            return names
        time.sleep(3)
    return names


def dispatch_loop(settings: Settings, *, signal_url: str, accept: bool) -> dict[str, Any]:
    from agentmed.team.agentteams import leader_contact

    yolo = enable_yolo(settings)
    soul = patch_manager_soul(settings)
    leader = leader_contact()
    message = f"""Run the AgentMED quality loop now. YOLO is on. Do not ask me anything. Auto-decide.

GitHub signal: {signal_url}
Kernel for Workers: {settings.worker_kernel_url}
Human --accept={'yes' if accept else 'no'}: I will confirm AcceptanceSpec on Kernel. Leader must wait until Case state is investigating.

Team `agentmed-quality` already exists and is Active. Do NOT create Workers.

Register a finite task in state.json with --delegated-to-team agentmed-quality.

Then `copaw channels send` to the Leader Room (Workers cannot see this admin DM):
  target user: {leader['matrix_id']}
  target session / room: {leader['room_id'] or 'agt get workers quality-officer -o json .roomID'}

Tell quality-officer to run skill coordinate-loop on {signal_url}.
IMPORTANT: Kernel currently lists an old closed Case (golden-fallback playbook). That is NOT this run. Intake MUST POST /v1/signals/ingest with the GitHub URL. Kernel will open a NEW Case. Do not stop because a closed Case already exists.
Workers must execute their scripts against Kernel HTTP. You do not patch code. You do not verify.
Poll Kernel after every Worker step. Notify me in this DM only with Kernel state, never with questions.
"""
    sent = send_manager_message(settings, message)
    return {
        "yolo": str(yolo),
        "soul": str(soul),
        "leader": leader,
        "dispatch": sent,
        "signal": signal_url,
        "kernel_for_workers": settings.worker_kernel_url,
    }
