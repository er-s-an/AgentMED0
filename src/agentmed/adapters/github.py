from __future__ import annotations

from typing import Any

import httpx


def fetch_github_issue(url: str, token: str = "") -> dict[str, Any]:
    parts = url.rstrip("/").split("/")
    if "github.com" not in url or "issues" not in parts:
        raise ValueError(f"not a GitHub issue URL: {url}")
    owner, repo, number = parts[-4], parts[-3], parts[-1]
    api = f"https://api.github.com/repos/{owner}/{repo}/issues/{number}"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "agentmed"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with httpx.Client(timeout=30) as client:
        response = client.get(api, headers=headers)
        response.raise_for_status()
        data = response.json()
    return {
        "url": data.get("html_url", url),
        "api_url": api,
        "owner": owner,
        "repo": repo,
        "number": int(number),
        "title": data.get("title") or "",
        "body": data.get("body") or "",
        "state": data.get("state"),
        "labels": [label.get("name") for label in data.get("labels", []) if isinstance(label, dict)],
        "user": (data.get("user") or {}).get("login"),
        "created_at": data.get("created_at"),
        "raw": {
            "id": data.get("id"),
            "node_id": data.get("node_id"),
            "updated_at": data.get("updated_at"),
        },
    }
