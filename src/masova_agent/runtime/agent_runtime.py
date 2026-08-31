"""
Unified AgentRuntime — single entry for chat, schedulers, triggers, and events.

Flow: goal → context → (optional LLM tool loop) → verify proposals → audit.
If LLM fails or is not configured: rule-based fallback still produces drafts.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Optional

from .audit import AuditLogger
from .models import (
    ActionProposal,
    AgentRunRequest,
    AgentRunResult,
    RiskTier,
    ToolCallStep,
)
from .policy import PolicyEngine
from . import proposal_store
from . import metrics
from . import run_store
from .circuit import allow_llm, record_failure, record_success

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
    from .circuit import reset_for_tests as reset_circuit

    reset_circuit()


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
        run_id = str(uuid.uuid4())
        request.run_id = run_id
        run_store.upsert_run({
            "run_id": run_id,
            "agent": request.agent_name,
            "status": "running",
            "store_id": request.store_id,
            "trigger_type": request.trigger_type,
            "reasoning_trace": [],
        })

        used_fallback = False
        tools_used: list[str] = []
        reasoning_trace: list[ToolCallStep] = []
        proposals: list[ActionProposal] = []
        output: dict[str, Any] = {}
        summary = ""
        status = "ok"
        error: str | None = None

        try:
            llm_result: dict[str, Any] | None = None
            try_llm = (
                request.prefer_llm
                and request.llm_runner is not None
                and allow_llm(request.agent_name)
            )
            if try_llm:
                try:
                    llm_result = await self._call_maybe_async(request.llm_runner, request)
                    record_success(request.agent_name)
                except Exception as e:
                    logger.warning(
                        "LLM path failed for %s: %s — using fallback",
                        request.agent_name,
                        e,
                    )
                    llm_result = None
                    error = f"llm_failed:{type(e).__name__}"
                    record_failure(request.agent_name)

            if llm_result is not None:
                output = dict(llm_result)
                tools_used = list(output.pop("tools_used", []) or [])
                reasoning_trace = self._extract_trace(output.pop("reasoning_trace", []))
                proposals = self._extract_proposals(output)
                summary = str(output.get("summary") or output.get("status") or "llm_ok")
            elif request.fallback is not None:
                used_fallback = True
                fb = await self._call_maybe_async(request.fallback)
                if not isinstance(fb, dict):
                    fb = {"result": fb}
                output = dict(fb)
                tools_used = list(output.pop("tools_used", []) or [])
                reasoning_trace = self._extract_trace(output.pop("reasoning_trace", []))
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
            if request.store_id:
                proposals = [
                    p for p in proposals
                    if not p.store_id or p.store_id == request.store_id
                ]
            # Notifications are not manager decision cards — keep them off the HITL queue.
            proposals = [p for p in proposals if not proposal_store.is_side_effect(p.to_dict())]
            # Never allow raw execute payloads through; normalize + persist
            kept_ids: set[str] = set()
            review_id = ""
            for p in proposals:
                if not p.requires_approval:
                    p.requires_approval = True
                if p.risk == RiskTier.EXECUTE:
                    p.risk = RiskTier.PROPOSE
                if not p.agent:
                    p.agent = request.agent_name
                if not p.store_id and request.store_id:
                    p.store_id = request.store_id
                # Stamp run_id so consoles can filter "this run" proposals
                payload = dict(p.payload or {})
                payload.setdefault("run_id", run_id)
                p.payload = payload
                if p.type == "DRAFT_REVIEW_REPLY" and not review_id:
                    review_id = str(payload.get("review_id") or payload.get("reviewId") or "")
                try:
                    rec = p.to_dict()
                    rec["run_id"] = run_id
                    proposal_store.save_proposal(rec)
                    kept_ids.add(str(p.proposal_id))
                except Exception as pe:
                    logger.warning("proposal persist failed: %s", pe)
            if request.store_id and request.agent_name:
                try:
                    proposal_store.supersede_stale_pending(
                        store_id=request.store_id,
                        agent=request.agent_name,
                        keep_ids=kept_ids,
                        keep_run_id=run_id,
                        review_id=review_id,
                    )
                except Exception as se:
                    logger.warning("proposal supersede failed: %s", se)

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
            reasoning_trace=reasoning_trace,
            output=output,
            run_id=run_id,
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

    def _extract_trace(self, raw: list[Any]) -> list[ToolCallStep]:
        out: list[ToolCallStep] = []
        for i, item in enumerate(raw or []):
            if isinstance(item, ToolCallStep):
                out.append(item)
            elif isinstance(item, dict):
                out.append(ToolCallStep(
                    index=item.get("index", i),
                    tool_name=str(item.get("tool_name") or item.get("tool") or ""),
                    args=dict(item.get("args") or {}),
                    result_status=str(item.get("result_status") or "ok"),
                    result_summary=str(item.get("result_summary") or "")[:500],
                    duration_ms=float(item.get("duration_ms") or 0.0),
                    at=str(item.get("at") or ""),
                ))
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
        if count <= 0:
            return []
        # One manager card — never explode counters (e.g. suggestions_sent=24) into N empty cards.
        return [
            ActionProposal(
                type=ptype,
                store_id=store_id or "",
                agent=agent_name,
                summary=str(output.get("summary") or f"{agent_name}: {count} action(s) need review"),
                rationale="Generated by rule-based fallback; manager approval required.",
                payload={
                    "source": "rule_fallback",
                    "count": count,
                    "agent_output": {k: output[k] for k in count_keys if k in output},
                },
            )
        ]
