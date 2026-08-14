from __future__ import annotations

from typing import Any

from agentmed.workloads import get_adapter


def _kotaemon():
    return get_adapter("kotaemon")


def run_eval(store_source: str) -> dict[str, Any]:
    return _kotaemon().run_eval({"lightrag_store.py": store_source})


def base_source() -> str:
    return _kotaemon().base_files()["lightrag_store.py"]


def known_bad_source() -> str:
    return _kotaemon().known_bad_files()["lightrag_store.py"]


def golden_source() -> str:
    return _kotaemon().golden_files()["lightrag_store.py"]
