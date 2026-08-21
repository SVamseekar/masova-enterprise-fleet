"""
Unified AgentRuntime — single entry for chat, schedulers, triggers, and events.

Flow: goal → context → (optional LLM tool loop) → verify proposals → audit.
If LLM fails or is not configured: rule-based fallback still produces drafts.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

from .audit import AuditLogger
from .models import (
    ActionProposal,
    AgentRunRequest,
    AgentRunResult,
    RiskTier,
)
from .policy import PolicyEngine
from . import proposal_store
from . import metrics

logger = logging.getLogger(__name__)

_runtime: Optional["AgentRuntime"] = None


def get_runtime() -> "AgentRuntime":
    global _runtime
    if _runtime is None:
        _runtime = AgentRuntime()
    return _runtime


def reset_runtime_for_tests() -> None:
    global _runtime
    _runtime = None


class AgentRuntime:
    """Shared run pipeline for all 8 agents."""

    def __init__(
        self,
        policy: PolicyEngine | None = None,
        audit: AuditLogger | None = None,
    ):
        self.policy = policy or PolicyEngine()
        self.audit = audit or AuditLogger()

    async def run(self, request: AgentRunRequest) -> AgentRunResult:
        started = time.perf_counter()
        allowed = self.policy.filter_allowlist(request.allowed_tools)
        request.allowed_tools = allowed

        used_fallback = False
        tools_used: list[str] = []
        proposals: list[ActionProposal] = []
        output: dict[str, Any] = {}
        summary = ""
        status = "ok"
        error: str | None = None

        try:
            llm_result: dict[str, Any] | None = None
            if request.prefer_llm and request.llm_runner is not None:
                try:
                    llm_result = await self._call_maybe_async(request.llm_runner, request)
                except Exception as e:
                    logger.warning(
                        "LLM path failed for %s: %s — using fallback",
                        request.agent_name,
                        e,
                    )
                    llm_result = None
                    error = f"llm_failed:{type(e).__name__}"

            if llm_result is not None:
                output = dict(llm_result)
                tools_used = list(output.pop("tools_used", []) or [])
                proposals = self._extract_proposals(output)
                summary = str(output.get("summary") or output.get("status") or "llm_ok")
            elif request.fallback is not None:
                used_fallback = True
                fb = await self._call_maybe_async(request.fallback)
                if not isinstance(fb, dict):
                    fb = {"result": fb}
                output = dict(fb)
                tools_used = list(output.pop("tools_used", []) or [])
                proposals = self._extract_proposals(output)
                # Rule agents often return status/ok fields without proposal objects
                if not proposals:
                    proposals = self._proposals_from_rule_output(
                        request.agent_name, request.store_id, output
                    )
                summary = str(
                    output.get("summary")
                    or output.get("status")
                    or f"{request.agent_name} fallback complete"
                )
                if output.get("error") and output.get("status") != "ok":
                    status = "error"
                    error = str(output.get("error"))
            else:
                status = "error"
                error = "no_llm_and_no_fallback"
                summary = "Agent run failed: no LLM runner and no fallback"

            proposals = self.policy.validate_proposals(proposals)
            # Never allow raw execute payloads through; normalize + persist
            for p in proposals:
                if not p.requires_approval:
                    p.requires_approval = True
                if p.risk == RiskTier.EXECUTE:
                    p.risk = RiskTier.PROPOSE
                if not p.agent:
                    p.agent = request.agent_name
                if not p.store_id and request.store_id:
                    p.store_id = request.store_id
                try:
                    proposal_store.save_proposal(p)
                except Exception as pe:
                    logger.warning("proposal persist failed: %s", pe)

        except Exception as e:
            logger.exception("AgentRuntime unhandled error for %s", request.agent_name)
            status = "error"
            error = str(e)
            summary = f"Agent run failed: {e}"

        latency_ms = (time.perf_counter() - started) * 1000
        result = AgentRunResult(
            agent_name=request.agent_name,
            trigger_type=request.trigger_type,
            status=status,
            used_fallback=used_fallback,
            store_id=request.store_id,
            summary=summary,
            proposals=proposals,
            tools_used=tools_used,
            output=output,
            error=error,
            latency_ms=latency_ms,
        )
        self.audit.log_run(result)
        metrics.record_run(
            agent=result.agent_name,
            used_fallback=result.used_fallback,
            proposal_count=len(result.proposals),
            llm_error=bool(result.error and str(result.error).startswith("llm_failed")),
            status=result.status,
        )
        return result

    async def _call_maybe_async(self, fn, *args) -> Any:
        if args:
            result = fn(*args)
        else:
            result = fn()
        if asyncio.iscoroutine(result):
            return await result
        return result

    def _extract_proposals(self, output: dict[str, Any]) -> list[ActionProposal]:
        raw = output.get("proposals") or []
        # Also lift single "proposal" key from tool-style outputs
        if not raw and isinstance(output.get("proposal"), dict):
            raw = [output["proposal"]]
        out: list[ActionProposal] = []
        for item in raw:
            if isinstance(item, ActionProposal):
                out.append(item)
            elif isinstance(item, dict):
                out.append(ActionProposal.from_dict(item))
        return out

    def _proposals_from_rule_output(
        self,
        agent_name: str,
        store_id: str | None,
        output: dict[str, Any],
    ) -> list[ActionProposal]:
        """Best-effort wrap of legacy rule-agent counters into proposals for audit."""
        type_map = {
            "inventory_reorder": "DRAFT_PURCHASE_ORDER",
            "churn_prevention": "DRAFT_CHURN_CAMPAIGN",
            "review_response": "DRAFT_REVIEW_REPLY",
            "shift_optimisation": "DRAFT_SHIFT_ROSTER",
            "kitchen_coach": "DRAFT_KITCHEN_BRIEF",
            "dynamic_pricing": "SUGGEST_PRICE_ADJUSTMENT",
            "demand_forecast": "WRITE_FORECAST",
        }
        ptype = type_map.get(agent_name)
        if not ptype:
            return []
        count_keys = (
            "pos_drafted",
            "campaigns_drafted",
            "suggestions_sent",
            "briefs_sent",
            "shifts_drafted",
            "forecasts_written",
            "drafts_created",
        )
        count = 0
        for k in count_keys:
            if isinstance(output.get(k), int) and output[k] > 0:
                count = output[k]
                break
        if count <= 0 and output.get("status") not in ("ok", None):
            return []
        if count <= 0 and not any(k in output for k in count_keys):
            # Still record a single summary proposal when run succeeded with empty counters
            if output.get("error"):
                return []
            return [
                ActionProposal(
                    type=ptype,
                    store_id=store_id or "",
                    agent=agent_name,
                    summary=f"{agent_name} completed via rule fallback",
                    rationale=str(output.get("summary") or output),
                    payload={"source": "rule_fallback", "output_keys": list(output.keys())},
                )
            ]
        proposals = []
        for i in range(max(count, 1) if count else 0):
            proposals.append(
                ActionProposal(
                    type=ptype,
                    store_id=store_id or "",
                    agent=agent_name,
                    summary=f"{agent_name} proposal {i + 1}/{count}",
                    rationale="Generated by rule-based fallback; manager approval required.",
                    payload={"source": "rule_fallback", "index": i, "agent_output": {
                        k: output[k] for k in count_keys if k in output
                    }},
                )
            )
        return proposals
