"""
Per-agent scoped credentials, replacing the single shared trigger key.

Live credential source: AGENT_API_KEYS (JSON array of {"key", "scopes"}).
Falls back to treating AGENT_TRIGGER_API_KEY as one master ("*"-scoped)
credential when AGENT_API_KEYS is unset — a migration path, not a
permanent duplicate mechanism (see spec's "Loading credentials" section).

Scope kinds: "trigger:<agent_id>", "read:registry", "read:proposals",
"resolve:proposals", "read:runs", "chat:manager". "*" grants all scopes.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Callable

from fastapi import Header, HTTPException, status

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentCredential:
    key: str
    scopes: frozenset[str]

    def has_scope(self, scope: str) -> bool:
        return "*" in self.scopes or scope in self.scopes


def load_credentials() -> dict[str, AgentCredential]:
    raw = os.getenv("AGENT_API_KEYS", "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error("AGENT_API_KEYS is not valid JSON: %s", e)
            parsed = None

        # Validate that parsed JSON is a list (expected shape)
        if not isinstance(parsed, list):
            logger.error("AGENT_API_KEYS must be a JSON array, got %s", type(parsed).__name__)
            parsed = None

        if parsed is None:
            parsed = []

        creds: dict[str, AgentCredential] = {}
        for entry in parsed:
            # Skip entries that aren't dicts
            if not isinstance(entry, dict):
                logger.warning("Skipping AGENT_API_KEYS entry that is not a dict: %s", type(entry).__name__)
                continue

            key = str(entry.get("key") or "").strip()
            if not key:
                continue
            scopes = frozenset(str(s) for s in (entry.get("scopes") or []))
            creds[key] = AgentCredential(key=key, scopes=scopes)
        return creds

    legacy = os.getenv("AGENT_TRIGGER_API_KEY", "").strip()
    if legacy:
        return {legacy: AgentCredential(key=legacy, scopes=frozenset({"*"}))}

    return {}


def require_scope(scope: str) -> Callable:
    async def _dependency(x_agent_api_key: str = Header(default="")) -> None:
        if not x_agent_api_key:
            logger.warning("scope check failed: missing_key scope=%s", scope)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing API key")

        creds = load_credentials()
        cred = creds.get(x_agent_api_key)
        if cred is None:
            logger.warning("scope check failed: unknown_key scope=%s", scope)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

        if not cred.has_scope(scope):
            logger.warning("scope check failed: insufficient_scope scope=%s", scope)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient scope")

    return _dependency
