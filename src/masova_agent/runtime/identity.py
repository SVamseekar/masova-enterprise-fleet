"""
Per-agent scoped credentials, replacing the single shared trigger key.

Live credential source: AGENT_API_KEYS (JSON array of {"key", "scopes"}).
Falls back to treating AGENT_TRIGGER_API_KEY as one master ("*"-scoped)
credential when AGENT_API_KEYS is unset — a migration path, not a
permanent duplicate mechanism (see spec's "Loading credentials" section).

Scope kinds: "trigger:<agent_id>", "read:registry", "read:proposals",
"resolve:proposals". "*" grants all scopes.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

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
            entries = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error("AGENT_API_KEYS is not valid JSON: %s", e)
            entries = []
        creds: dict[str, AgentCredential] = {}
        for entry in entries:
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
