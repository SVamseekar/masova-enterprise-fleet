"""Shared HTTP helpers for ops agents (AGENT_TOKEN outbound auth)."""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


def backend_url() -> str:
    return (os.getenv("BACKEND_URL") or "http://127.0.0.1:8080").rstrip("/")


def agent_token() -> str:
    from ..services import demo_backend

    if demo_backend.demo_mode():
        return os.getenv("AGENT_TOKEN") or "demo-agent-token"
    return os.getenv("AGENT_TOKEN", "")



def agent_headers() -> dict[str, str]:
    token = agent_token()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def unwrap_list(data: Any) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("content") or data.get("items") or data.get("topItems") or []
    return []


def focus_store_list(stores: list, scope: Optional[str]) -> list:
    """Scope a store list to one id/code. Unknown scope does not fall through to the fleet."""
    if not scope:
        return stores
    focused = [
        s for s in stores
        if isinstance(s, dict) and (s.get("id") == scope or s.get("code") == scope)
    ]
    if focused:
        return focused
    return [{"id": scope, "name": scope, "code": scope}]


async def get_json(
    client: httpx.AsyncClient,
    path: str,
    *,
    params: Optional[dict] = None,
) -> tuple[int, Any]:
    from ..services import demo_backend

    if demo_backend.demo_mode():
        return 200, demo_backend.get(path, params)

    url = path if path.startswith("http") else f"{backend_url()}{path}"
    res = await client.get(url, params=params, headers=agent_headers())
    try:
        body = res.json() if res.content else None
    except Exception:
        body = res.text
    return res.status_code, body


async def post_json(
    client: httpx.AsyncClient,
    path: str,
    payload: dict,
) -> tuple[int, Any]:
    from ..services import demo_backend

    if demo_backend.demo_mode():
        return 200, demo_backend.post(path, payload)

    url = path if path.startswith("http") else f"{backend_url()}{path}"
    res = await client.post(url, json=payload, headers=agent_headers())
    try:
        body = res.json() if res.content else None
    except Exception:
        body = res.text
    return res.status_code, body

