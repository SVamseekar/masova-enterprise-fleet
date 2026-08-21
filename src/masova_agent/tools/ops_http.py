"""Shared HTTP helpers for ops agents (AGENT_TOKEN outbound auth)."""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


def backend_url() -> str:
    return os.getenv("BACKEND_URL", "http://192.168.50.88:8080").rstrip("/")


def agent_token() -> str:
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
        return data.get("content") or []
    return []


async def get_json(
    client: httpx.AsyncClient,
    path: str,
    *,
    params: Optional[dict] = None,
) -> tuple[int, Any]:
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
    url = path if path.startswith("http") else f"{backend_url()}{path}"
    res = await client.post(url, json=payload, headers=agent_headers())
    try:
        body = res.json() if res.content else None
    except Exception:
        body = res.text
    return res.status_code, body
