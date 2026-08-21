"""Unit tests for AgentRuntime, policy, and audit (no live LLM/backend)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from masova_agent.runtime import (
    ActionProposal,
    AgentRunRequest,
    AgentRuntime,
    PolicyEngine,
    RiskTier,
)
from masova_agent.runtime.agent_runtime import reset_runtime_for_tests
from masova_agent.runtime.policy import DEFAULT_TOOL_REGISTRY


@pytest.fixture(autouse=True)
def _reset():
    reset_runtime_for_tests()
    yield
    reset_runtime_for_tests()


class TestPolicyEngine:
    def test_execute_tools_never_allowed(self):
        pe = PolicyEngine()
        assert pe.is_allowed("patch_menu_price", ["patch_menu_price"]) is False
        assert pe.is_allowed("execute_refund", ["execute_refund"]) is False

    def test_filter_allowlist_drops_execute(self):
        pe = PolicyEngine()
        cleaned = pe.filter_allowlist([
            "get_order_status",
            "patch_menu_price",
            "draft_purchase_order",
        ])
        assert "get_order_status" in cleaned
        assert "draft_purchase_order" in cleaned
        assert "patch_menu_price" not in cleaned

    def test_propose_tools_allowed_when_listed(self):
        pe = PolicyEngine()
        assert pe.is_allowed("cancel_order", ["cancel_order"]) is True
        assert pe.tier_for("cancel_order") == RiskTier.PROPOSE

    def test_validate_proposals_forces_approval(self):
        pe = PolicyEngine(max_proposals=2)
        props = [
            ActionProposal(
                type="X", store_id="s1", summary="a", rationale="r",
                requires_approval=False, risk=RiskTier.READ,
            ),
            ActionProposal(type="Y", store_id="s1", summary="b", rationale="r"),
            ActionProposal(type="Z", store_id="s1", summary="c", rationale="r"),
        ]
        out = pe.validate_proposals(props)
        assert len(out) == 2
        assert all(p.requires_approval for p in out)
        assert all(p.risk == RiskTier.PROPOSE for p in out)

    def test_registry_has_no_execute_on_customer_tools(self):
        for name in (
            "get_order_status", "submit_complaint", "cancel_order", "request_refund",
        ):
            assert DEFAULT_TOOL_REGISTRY[name].tier != RiskTier.EXECUTE


class TestAgentRuntime:
    @pytest.mark.asyncio
    async def test_fallback_when_no_llm(self):
        runtime = AgentRuntime()

        async def fb():
            return {
                "status": "ok",
                "pos_drafted": 2,
                "summary": "drafted 2 POs",
            }

        result = await runtime.run(AgentRunRequest(
            agent_name="inventory_reorder",
            trigger_type="scheduled",
            store_id="store-1",
            prefer_llm=True,
            llm_runner=None,
            fallback=fb,
        ))
        assert result.status == "ok"
        assert result.used_fallback is True
        assert result.latency_ms >= 0
        assert len(result.proposals) >= 1
        assert all(p.requires_approval for p in result.proposals)
        assert runtime.audit.records[-1]["used_fallback"] is True

    @pytest.mark.asyncio
    async def test_llm_success_skips_fallback(self):
        runtime = AgentRuntime()
        fallback_called = {"v": False}

        async def llm(req):
            return {
                "summary": "llm ok",
                "tools_used": ["read_inventory_levels", "draft_purchase_order"],
                "proposals": [{
                    "type": "DRAFT_PURCHASE_ORDER",
                    "store_id": "s1",
                    "summary": "Reorder flour",
                    "rationale": "Below min stock for 48h demand",
                    "payload": {"qty": 20},
                }],
            }

        async def fb():
            fallback_called["v"] = True
            return {"status": "ok"}

        result = await runtime.run(AgentRunRequest(
            agent_name="inventory_reorder",
            trigger_type="manual",
            allowed_tools=["read_inventory_levels", "draft_purchase_order", "patch_menu_price"],
            llm_runner=llm,
            fallback=fb,
        ))
        assert result.used_fallback is False
        assert fallback_called["v"] is False
        assert result.tools_used == ["read_inventory_levels", "draft_purchase_order"]
        assert result.proposals[0].type == "DRAFT_PURCHASE_ORDER"
        assert result.proposals[0].rationale
        # EXECUTE stripped from allowlist
        assert "patch_menu_price" not in result.output.get("allowed_tools", [])

    @pytest.mark.asyncio
    async def test_llm_failure_uses_fallback(self):
        runtime = AgentRuntime()

        async def llm(req):
            raise RuntimeError("provider down")

        async def fb():
            return {"status": "ok", "suggestions_sent": 1, "summary": "rule pricing"}

        result = await runtime.run(AgentRunRequest(
            agent_name="dynamic_pricing",
            trigger_type="scheduled",
            llm_runner=llm,
            fallback=fb,
        ))
        assert result.used_fallback is True
        assert result.status == "ok"
        assert "llm_failed" in (result.error or "")
        assert len(result.proposals) >= 1
        assert result.proposals[0].type == "SUGGEST_PRICE_ADJUSTMENT"

    @pytest.mark.asyncio
    async def test_no_llm_no_fallback_errors(self):
        runtime = AgentRuntime()
        result = await runtime.run(AgentRunRequest(
            agent_name="orphan",
            trigger_type="manual",
        ))
        assert result.status == "error"
        assert result.used_fallback is False

    @pytest.mark.asyncio
    async def test_audit_redacts_sensitive_keys(self):
        runtime = AgentRuntime()
        # inject sensitive into record via summary path is not enough —
        # audit redacts nested dicts when logging; test redact directly
        redacted = runtime.audit._redact({"token": "secret", "ok": 1})
        assert redacted["token"] == "[REDACTED]"
        assert redacted["ok"] == 1


class TestActionProposalShape:
    def test_to_dict(self):
        p = ActionProposal(
            type="DRAFT_PURCHASE_ORDER",
            store_id="s1",
            summary="PO for flour",
            rationale="stock below threshold",
            payload={"qty": 5},
        )
        d = p.to_dict()
        assert d["requires_approval"] is True
        assert d["risk"] == "PROPOSE"
        assert d["payload"]["qty"] == 5
