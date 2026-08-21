"""Structured audit logging for agent runs."""

from __future__ import annotations

import json
import logging
from typing import Any

from .models import AgentRunResult

logger = logging.getLogger("masova_agent.audit")


class AuditLogger:
    """
    Emits structured run logs: agent, trigger, store_id, tools, proposals,
    fallback flag, latency. Avoids dumping raw PII (tokens, full JWT, etc.).
    """

    SENSITIVE_KEYS = frozenset({
        "raw_token", "token", "password", "authorization", "api_key",
        "jwt", "secret", "credit_card",
    })

    def __init__(self, sink: logging.Logger | None = None):
        self._log = sink or logger
        self.records: list[dict[str, Any]] = []

    def log_run(self, result: AgentRunResult) -> dict[str, Any]:
        proposal_summaries = [
            {
                "type": p.type,
                "summary": (p.summary or "")[:200],
                "rationale": (p.rationale or "")[:200],
                "store_id": p.store_id,
            }
            for p in result.proposals[:20]
        ]
        record = {
            "event": "agent_run",
            "run_id": result.run_id,
            "agent": result.agent_name,
            "trigger_type": result.trigger_type,
            "store_id": result.store_id,
            "status": result.status,
            "used_fallback": result.used_fallback,
            "tools_used": list(result.tools_used),
            "proposal_count": len(result.proposals),
            "proposal_types": [p.type for p in result.proposals],
            "proposal_summaries": proposal_summaries,
            "summary": (result.summary or "")[:500],
            "latency_ms": round(result.latency_ms, 2),
            "error": result.error,
        }
        record = self._redact(record)
        self.records.append(record)
        self._log.info("agent_audit %s", json.dumps(record, default=str))
        return record

    def _redact(self, obj: Any) -> Any:
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                if str(k).lower() in self.SENSITIVE_KEYS:
                    out[k] = "[REDACTED]"
                else:
                    out[k] = self._redact(v)
            return out
        if isinstance(obj, list):
            return [self._redact(x) for x in obj]
        return obj
