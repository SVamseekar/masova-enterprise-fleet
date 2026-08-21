"""Helpers for ops agents to run through AgentRuntime with rule fallbacks."""

from __future__ import annotations

from typing import Any, Optional

from .agent_runtime import get_runtime
from .models import AgentRunRequest, FallbackFn, LlmRunnerFn
from .ops_llm import ops_prefer_llm


# Default tool allowlists per agent (no EXECUTE).
AGENT_ALLOWLISTS: dict[str, list[str]] = {
    "support_chat": [
        "get_order_status",
        "get_menu_items",
        "get_store_hours",
        "get_loyalty_points",
        "get_store_wait_time",
        "submit_complaint",
        "cancel_order",
        "request_refund",
    ],
    "demand_forecast": [
        "list_stores",
        "read_order_metrics",
        "compute_wma_forecast",
        "write_forecast",
        "notify_managers",
    ],
    "inventory_reorder": [
        "list_stores",
        "list_low_stock",
        "read_inventory_levels",
        "get_forecast_snippet",
        "create_draft_po",
        "draft_purchase_order",
        "notify_managers",
        "notify_manager",
    ],
    "churn_prevention": [
        "list_stores",
        "read_churn_segment",
        "get_top_items",
        "create_draft_campaign",
        "draft_churn_campaign",
        "notify_managers",
    ],
    "review_response": [
        "get_order_context",
        "submit_review_draft_notification",
        "draft_review_reply",
        "notify_managers",
    ],
    "shift_optimisation": [
        "list_stores",
        "read_staff_slots",
        "get_forecast_snippet",
        "create_draft_shifts",
        "draft_shift_roster",
        "notify_managers",
    ],
    "kitchen_coach": [
        "list_stores",
        "read_kitchen_metrics",
        "draft_kitchen_brief",
        "notify_managers",
    ],
    "dynamic_pricing": [
        "list_stores",
        "count_active_orders",
        "count_recent_orders",
        "get_top_items",
        "get_slow_items",
        "read_order_metrics",
        "compute_pricing_signal",
        "propose_price_suggestion",
        "suggest_price_adjustment",
        "notify_managers",
    ],
}


async def run_ops_agent(
    agent_name: str,
    trigger_type: str,
    fallback: FallbackFn,
    *,
    store_id: Optional[str] = None,
    goal: str = "",
    context: Optional[dict[str, Any]] = None,
    llm_runner: Optional[LlmRunnerFn] = None,
    prefer_llm: Optional[bool] = None,
    allowed_tools: Optional[list[str]] = None,
) -> dict[str, Any]:
    """
    Run an ops agent through the shared runtime.

    prefer_llm defaults to ops_prefer_llm() (true only when an API key is set,
    unless OPS_PREFER_LLM overrides). When prefer_llm and llm_runner are set,
    LLM tool loop is tried first; rule fallback always remains available.
    """
    if prefer_llm is None:
        prefer_llm = ops_prefer_llm() and llm_runner is not None
    else:
        prefer_llm = prefer_llm and llm_runner is not None

    request = AgentRunRequest(
        agent_name=agent_name,
        trigger_type=trigger_type,
        store_id=store_id,
        goal=goal or f"Run {agent_name}",
        context=context or {},
        allowed_tools=list(allowed_tools or AGENT_ALLOWLISTS.get(agent_name, [])),
        fallback=fallback,
        llm_runner=llm_runner,
        prefer_llm=prefer_llm,
    )
    result = await get_runtime().run(request)
    # Preserve legacy agent response shape for HTTP triggers + tests
    payload = dict(result.output) if result.output else {}
    if result.status == "error" and result.error and "error" not in payload:
        payload["error"] = result.error
    if "status" not in payload and result.status == "ok":
        payload.setdefault("status", "ok")
    # Surface LLM rationale for manager-facing consumers
    if result.summary and "summary" not in payload:
        payload["summary"] = result.summary
    rationale = payload.get("rationale")
    if not rationale and result.proposals:
        rationale = result.proposals[0].rationale
    payload["_runtime"] = {
        "run_id": result.run_id,
        "agent_name": result.agent_name,
        "trigger_type": result.trigger_type,
        "used_fallback": result.used_fallback,
        "latency_ms": result.latency_ms,
        "proposal_count": len(result.proposals),
        "proposals": [p.to_dict() for p in result.proposals],
        "summary": result.summary,
        "status": result.status,
        "tools_used": list(result.tools_used),
        "rationale": rationale or "",
    }
    return payload
