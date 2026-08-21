"""HITL policy: tool allowlists, max proposals, block Execute tier."""

from __future__ import annotations

import logging
from typing import Iterable

from .models import ActionProposal, RiskTier, ToolRisk

logger = logging.getLogger(__name__)


# Default registry of known tools and their risk tiers.
# EXECUTE tools must never appear on agent allowlists.
DEFAULT_TOOL_REGISTRY: dict[str, ToolRisk] = {
    # Customer chat — read
    "get_order_status": ToolRisk("get_order_status", RiskTier.READ),
    "get_menu_items": ToolRisk("get_menu_items", RiskTier.READ),
    "get_store_hours": ToolRisk("get_store_hours", RiskTier.READ),
    "get_loyalty_points": ToolRisk("get_loyalty_points", RiskTier.READ),
    "get_store_wait_time": ToolRisk("get_store_wait_time", RiskTier.READ),
    # Customer chat — propose (pending manager approval via backend)
    "submit_complaint": ToolRisk("submit_complaint", RiskTier.PROPOSE),
    "cancel_order": ToolRisk("cancel_order", RiskTier.PROPOSE),
    "request_refund": ToolRisk("request_refund", RiskTier.PROPOSE),
    # Ops — READ
    "list_stores": ToolRisk("list_stores", RiskTier.READ),
    "list_low_stock": ToolRisk("list_low_stock", RiskTier.READ),
    "read_inventory_levels": ToolRisk("read_inventory_levels", RiskTier.READ),
    "get_forecast_snippet": ToolRisk("get_forecast_snippet", RiskTier.READ),
    "count_active_orders": ToolRisk("count_active_orders", RiskTier.READ),
    "count_recent_orders": ToolRisk("count_recent_orders", RiskTier.READ),
    "get_top_items": ToolRisk("get_top_items", RiskTier.READ),
    "get_slow_items": ToolRisk("get_slow_items", RiskTier.READ),
    "get_order_context": ToolRisk("get_order_context", RiskTier.READ),
    "read_churn_segment": ToolRisk("read_churn_segment", RiskTier.READ),
    "read_staff_slots": ToolRisk("read_staff_slots", RiskTier.READ),
    "read_kitchen_metrics": ToolRisk("read_kitchen_metrics", RiskTier.READ),
    "read_order_metrics": ToolRisk("read_order_metrics", RiskTier.READ),
    # Ops — COMPUTE
    "compute_wma_forecast": ToolRisk("compute_wma_forecast", RiskTier.COMPUTE),
    "compute_pricing_signal": ToolRisk("compute_pricing_signal", RiskTier.COMPUTE),
    # Ops — PROPOSE only
    "create_draft_po": ToolRisk("create_draft_po", RiskTier.PROPOSE),
    "draft_purchase_order": ToolRisk("draft_purchase_order", RiskTier.PROPOSE),
    "notify_managers": ToolRisk("notify_managers", RiskTier.PROPOSE),
    "notify_manager": ToolRisk("notify_manager", RiskTier.PROPOSE),
    "propose_price_suggestion": ToolRisk("propose_price_suggestion", RiskTier.PROPOSE),
    "suggest_price_adjustment": ToolRisk("suggest_price_adjustment", RiskTier.PROPOSE),
    "create_draft_campaign": ToolRisk("create_draft_campaign", RiskTier.PROPOSE),
    "draft_churn_campaign": ToolRisk("draft_churn_campaign", RiskTier.PROPOSE),
    "create_draft_shifts": ToolRisk("create_draft_shifts", RiskTier.PROPOSE),
    "draft_shift_roster": ToolRisk("draft_shift_roster", RiskTier.PROPOSE),
    "submit_review_draft_notification": ToolRisk(
        "submit_review_draft_notification", RiskTier.PROPOSE
    ),
    "draft_review_reply": ToolRisk("draft_review_reply", RiskTier.PROPOSE),
    "draft_kitchen_brief": ToolRisk("draft_kitchen_brief", RiskTier.PROPOSE),
    "write_forecast": ToolRisk("write_forecast", RiskTier.PROPOSE),
    # Explicitly blocked (must never be allowlisted)
    "patch_menu_price": ToolRisk("patch_menu_price", RiskTier.EXECUTE, "Manager-only price write"),
    "execute_purchase_order": ToolRisk("execute_purchase_order", RiskTier.EXECUTE),
    "execute_refund": ToolRisk("execute_refund", RiskTier.EXECUTE),
    "cancel_order_immediate": ToolRisk("cancel_order_immediate", RiskTier.EXECUTE),
    "send_campaign_live": ToolRisk("send_campaign_live", RiskTier.EXECUTE),
    "confirm_shifts": ToolRisk("confirm_shifts", RiskTier.EXECUTE),
}


class PolicyEngine:
    """Enforces HITL rules for tools and proposals."""

    def __init__(
        self,
        registry: dict[str, ToolRisk] | None = None,
        max_proposals: int = 50,
        max_tool_calls: int = 12,
    ):
        self.registry = dict(registry or DEFAULT_TOOL_REGISTRY)
        self.max_proposals = max_proposals
        self.max_tool_calls = max_tool_calls

    def register_tool(self, tool: ToolRisk) -> None:
        self.registry[tool.name] = tool

    def tier_for(self, tool_name: str) -> RiskTier | None:
        entry = self.registry.get(tool_name)
        return entry.tier if entry else None

    def is_allowed(self, tool_name: str, allowed_tools: Iterable[str]) -> bool:
        """True if tool is on the agent allowlist and is not EXECUTE."""
        if tool_name not in set(allowed_tools):
            return False
        tier = self.tier_for(tool_name)
        if tier is None:
            logger.warning("Unknown tool %s — denied by default", tool_name)
            return False
        if tier == RiskTier.EXECUTE:
            logger.error("Blocked EXECUTE tool on allowlist attempt: %s", tool_name)
            return False
        return True

    def filter_allowlist(self, tools: Iterable[str]) -> list[str]:
        """Drop unknown and EXECUTE tools from a proposed allowlist."""
        cleaned: list[str] = []
        for name in tools:
            tier = self.tier_for(name)
            if tier is None:
                logger.warning("Dropping unregistered tool from allowlist: %s", name)
                continue
            if tier == RiskTier.EXECUTE:
                logger.error("Dropping EXECUTE tool from allowlist: %s", name)
                continue
            cleaned.append(name)
        return cleaned

    def validate_proposals(self, proposals: list[ActionProposal]) -> list[ActionProposal]:
        """Cap proposal count; force requires_approval and PROPOSE risk."""
        out: list[ActionProposal] = []
        for p in proposals[: self.max_proposals]:
            if p.risk == RiskTier.EXECUTE:
                logger.error("Dropping EXECUTE proposal type=%s", p.type)
                continue
            p.risk = RiskTier.PROPOSE
            p.requires_approval = True
            out.append(p)
        if len(proposals) > self.max_proposals:
            logger.warning(
                "Truncated proposals from %d to %d",
                len(proposals),
                self.max_proposals,
            )
        return out
