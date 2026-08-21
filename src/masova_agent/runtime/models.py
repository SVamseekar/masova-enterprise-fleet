"""Shared types for the agent platform run pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Optional
import uuid


class RiskTier(str, Enum):
    """HITL risk classification for tools and proposals."""

    READ = "READ"  # free — auto
    COMPUTE = "COMPUTE"  # free — auto
    PROPOSE = "PROPOSE"  # draft + manager notify
    EXECUTE = "EXECUTE"  # never on agent allowlists


class ProposalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class ToolRisk:
    """Registry entry for a named tool."""

    name: str
    tier: RiskTier
    description: str = ""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ActionProposal:
    """
    Canonical high-risk outcome that requires manager approval.

    Agents never auto-write final business state; they emit proposals.
    Final execute still happens in platform UI/backend after approval.
    """

    type: str
    store_id: str
    summary: str
    rationale: str
    risk: RiskTier = RiskTier.PROPOSE
    payload: dict[str, Any] = field(default_factory=dict)
    requires_approval: bool = True
    proposal_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent: str = ""
    status: ProposalStatus = ProposalStatus.PENDING
    created_at: str = field(default_factory=_utc_now_iso)
    idempotency_key: str = ""
    resolution_note: str = ""
    resolved_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["risk"] = self.risk.value if isinstance(self.risk, RiskTier) else self.risk
        d["status"] = (
            self.status.value if isinstance(self.status, ProposalStatus) else self.status
        )
        return d

    @classmethod
    def from_dict(cls, item: dict[str, Any], *, agent: str = "") -> "ActionProposal":
        risk = item.get("risk", RiskTier.PROPOSE)
        if isinstance(risk, str):
            try:
                risk = RiskTier(risk)
            except ValueError:
                risk = RiskTier.PROPOSE
        status = item.get("status", ProposalStatus.PENDING)
        if isinstance(status, str):
            try:
                status = ProposalStatus(status)
            except ValueError:
                status = ProposalStatus.PENDING
        kwargs: dict[str, Any] = {
            "type": str(item.get("type", "UNKNOWN")),
            "store_id": str(item.get("store_id") or ""),
            "summary": str(item.get("summary") or ""),
            "rationale": str(item.get("rationale") or ""),
            "risk": risk if isinstance(risk, RiskTier) else RiskTier.PROPOSE,
            "payload": dict(item.get("payload") or {}),
            "requires_approval": bool(item.get("requires_approval", True)),
            "agent": str(item.get("agent") or agent or ""),
            "status": status if isinstance(status, ProposalStatus) else ProposalStatus.PENDING,
            "created_at": str(item.get("created_at") or _utc_now_iso()),
            "idempotency_key": str(
                item.get("idempotency_key")
                or (item.get("payload") or {}).get("idempotency_key")
                or ""
            ),
            "resolution_note": str(item.get("resolution_note") or ""),
            "resolved_at": str(item.get("resolved_at") or ""),
        }
        if item.get("proposal_id"):
            kwargs["proposal_id"] = str(item["proposal_id"])
        return cls(**kwargs)


# Optional async/sync fallback producing a result dict and optional proposals.
FallbackFn = Callable[[], Awaitable[dict[str, Any]] | dict[str, Any]]
# Optional LLM/tool loop hook (injectable; mocked in tests).
LlmRunnerFn = Callable[["AgentRunRequest"], Awaitable[dict[str, Any]] | dict[str, Any]]


@dataclass
class AgentRunRequest:
    """Unified input for every agent run (chat, cron, trigger, RabbitMQ)."""

    agent_name: str
    trigger_type: str  # scheduled | manual | chat | event
    store_id: Optional[str] = None
    goal: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    # Tools allowed for this agent (names must be registered with non-EXECUTE tier)
    allowed_tools: list[str] = field(default_factory=list)
    # Rule-based path when LLM is unavailable or fails
    fallback: Optional[FallbackFn] = None
    # Optional LLM multi-step runner; if None, fallback (or empty) is used
    llm_runner: Optional[LlmRunnerFn] = None
    max_tool_calls: int = 12
    prefer_llm: bool = True


@dataclass
class AgentRunResult:
    """Outcome of a unified agent run."""

    agent_name: str
    trigger_type: str
    status: str  # ok | error | skipped
    used_fallback: bool = False
    store_id: Optional[str] = None
    summary: str = ""
    proposals: list[ActionProposal] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    output: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    latency_ms: float = 0.0
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "agent_name": self.agent_name,
            "trigger_type": self.trigger_type,
            "status": self.status,
            "used_fallback": self.used_fallback,
            "store_id": self.store_id,
            "summary": self.summary,
            "proposals": [p.to_dict() for p in self.proposals],
            "tools_used": self.tools_used,
            "output": self.output,
            "error": self.error,
            "latency_ms": self.latency_ms,
        }
