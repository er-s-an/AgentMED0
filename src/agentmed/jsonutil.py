from __future__ import annotations

import json
import re


def parse_json_object(text: str) -> dict:
    """Parse a JSON object from model output, stripping markdown fences."""
    stripped = (text or "").strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, count=1, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped, count=1)
        stripped = stripped.strip()
    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("response is not a JSON object") from None
        try:
            obj = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError("response is not a JSON object") from exc
    if not isinstance(obj, dict):
        raise ValueError("response is not a JSON object")
    return obj
