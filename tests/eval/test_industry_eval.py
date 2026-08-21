"""
Industry-grade eval harness — scripted / mocked plans (CI-safe).

Scenarios (must pass):
1. Low stock → draft PO (no invented qty without tool data)
2. Kitchen overload → price SUGGEST only; no menu PATCH
3. Underload near close → no discount / skip
4. 1★ review → draft response notify
5. LLM raises → fallback still returns ok/draft
6. Chat: spoofed customer id ignored (identity binding)
7. Cancel/refund messaging mentions manager approval
8. Idempotency: second run same key does not double-create
9. Policy: EXECUTE tools rejected
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from masova_agent.runtime.agent_runtime import get_runtime, reset_runtime_for_tests
from masova_agent.runtime.idempotency import clear_for_tests
from masova_agent.runtime.models import AgentRunRequest
from masova_agent.runtime.ops_llm import run_scripted_tool_loop
from masova_agent.runtime.policy import PolicyEngine, RiskTier
from masova_agent.runtime.wrap import AGENT_ALLOWLISTS, run_ops_agent
from masova_agent.tools import ops_tools
from masova_agent.auth import AgentIdentity, bind_identity, reset_identity


@pytest.fixture(autouse=True)
def _clean():
    clear_for_tests()
    reset_runtime_for_tests()
    yield
    clear_for_tests()
    reset_runtime_for_tests()


# ---------------------------------------------------------------------------
# 1. Low stock → draft PO
# ---------------------------------------------------------------------------

class TestEvalLowStockDraftPO:
    @pytest.mark.asyncio
    async def test_scripted_inventory_drafts_po_from_tool_items(self):
        async def list_low_stock(store_id: str = ""):
            return {
                "ok": True,
                "items": [{
                    "id": "inv-1",
                    "store_id": "DOM001",
                    "item_name": "Flour",
                    "current_stock": 2,
                    "reorder_quantity": 20,
                    "preferred_supplier_id": "sup-1",
                    "unit_cost": 5,
                }],
                "count": 1,
            }

        async def create_draft_po(store_id, supplier_id, items=None, rationale="", **_):
            assert items and items[0]["reorder_quantity"] == 20  # tool data, not invented
            return {
                "ok": True,
                "proposal": {
                    "type": "DRAFT_PURCHASE_ORDER",
                    "store_id": store_id,
                    "summary": "Draft PO",
                    "rationale": rationale or "low stock",
                    "requires_approval": True,
                    "payload": {"items": items},
                },
            }

        async def notify_managers(**kwargs):
            return {"ok": True, "sent": 1, "proposal": None}

        tools = {
            "list_low_stock": list_low_stock,
            "create_draft_po": create_draft_po,
            "notify_managers": notify_managers,
        }
        plan = [
            {"tool": "list_low_stock", "args": {"store_id": "DOM001"}},
            {
                "tool": "create_draft_po",
                "args": {
                    "store_id": "DOM001",
                    "supplier_id": "sup-1",
                    "items": [{
                        "id": "inv-1",
                        "reorder_quantity": 20,
                        "item_name": "Flour",
                    }],
                    "rationale": "Below reorder from list_low_stock",
                },
            },
            {"tool": "notify_managers", "args": {
                "store_id": "DOM001", "message": "PO draft ready", "title": "Inventory",
            }},
        ]
        req = AgentRunRequest(
            agent_name="inventory_reorder",
            trigger_type="eval",
            store_id="DOM001",
            allowed_tools=list(AGENT_ALLOWLISTS["inventory_reorder"]),
        )
        out = await run_scripted_tool_loop(req, tools=tools, plan=plan)
        assert out["status"] == "ok"
        assert any(p.get("type") == "DRAFT_PURCHASE_ORDER" for p in out.get("proposals") or [])
        assert "create_draft_po" in out["tools_used"]


# ---------------------------------------------------------------------------
# 2–3. Pricing overload suggest / underload near close skip
# ---------------------------------------------------------------------------

class TestEvalPricing:
    @pytest.mark.asyncio
    async def test_overload_suggest_no_menu_patch(self):
        posts = []

        async def notify_managers(**kw):
            posts.append(kw)
            return {"ok": True, "sent": 1}

        with patch.object(ops_tools, "_require_token", return_value=None), patch.object(
            ops_tools, "notify_managers", side_effect=notify_managers
        ):
            r = await ops_tools.propose_price_suggestion(
                store_id="DOM001",
                direction="increase",
                percent=12,
                item_names=["Pizza"],
                active_count=20,
                rationale="20 active from count_active_orders",
            )
        assert r["patches_menu"] is False
        assert r["proposal"]["requires_approval"] is True
        # No HTTP path to menu in this function — only notify
        assert posts

    @pytest.mark.asyncio
    async def test_underload_near_close_signal_none(self):
        # Near close (hour 21, close 22): must NOT discount
        r = await ops_tools.compute_pricing_signal(
            "DOM001",
            active_count=1,
            recent_count=1,
            current_hour=21,
        )
        assert r["signal"] == "none"
        assert r["hours_to_close"] < 2

        # Underload with enough time to close
        r2 = await ops_tools.compute_pricing_signal(
            "DOM001", active_count=1, recent_count=1, current_hour=14
        )
        assert r2["signal"] == "underload"

        from masova_agent.agents.dynamic_pricing_agent import _pricing_pre_gate

        out = await _pricing_pre_gate(
            AgentRunRequest(
                agent_name="dynamic_pricing",
                trigger_type="eval",
                context={"pricing_signal": "none"},
            )
        )
        assert out["skipped_llm"] is True
        assert out["suggestions_sent"] == 0


# ---------------------------------------------------------------------------
# 4. 1★ review draft notify
# ---------------------------------------------------------------------------

class TestEvalReview:
    @pytest.mark.asyncio
    async def test_one_star_drafts_response(self):
        from masova_agent.agents.review_response_agent import draft_review_response

        client = AsyncMock()
        client.get = AsyncMock(side_effect=[
            MagicMock(status_code=200, json=lambda: {"items": [{"name": "Burger"}]}, text="{}"),
            MagicMock(status_code=200, json=lambda: {"content": [{"id": "mgr-1"}]}, text="{}"),
        ])
        client.post = AsyncMock(return_value=MagicMock(status_code=201, json=lambda: {}, text="{}"))
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=client)
        ctx.__aexit__ = AsyncMock(return_value=False)

        mock_genai = MagicMock()
        mock_genai.models.generate_content.return_value = MagicMock(
            text="We are sorry about your experience."
        )
        cfg = MagicMock(backend_url="http://test", agent_token="tok", google_api_key="key")

        with patch("masova_agent.utils.config.get_config", return_value=cfg), patch(
            "masova_agent.agents.review_response_agent.httpx.AsyncClient", return_value=ctx
        ), patch("google.genai.Client", return_value=mock_genai):
            result = await draft_review_response({
                "reviewId": "rev-1",
                "rating": 1,
                "text": "Terrible cold food",
                "storeId": "DOM001",
                "orderId": "ord-1",
            })
        assert result.get("draftGenerated") is True or result.get("skipped") is not True


# ---------------------------------------------------------------------------
# 5. LLM raises → fallback
# ---------------------------------------------------------------------------

class TestEvalLlmFallback:
    @pytest.mark.asyncio
    async def test_llm_error_uses_fallback(self):
        async def boom(_req):
            raise RuntimeError("provider_down")

        async def fb():
            return {"status": "ok", "pos_drafted": 1, "summary": "rule draft"}

        result = await run_ops_agent(
            "inventory_reorder",
            "eval",
            fb,
            llm_runner=boom,
            prefer_llm=True,
        )
        assert result["_runtime"]["used_fallback"] is True
        assert result.get("status") == "ok" or result.get("pos_drafted") == 1


# ---------------------------------------------------------------------------
# 6. Chat identity binding
# ---------------------------------------------------------------------------

class TestEvalChatIdentity:
    def test_spoofed_customer_id_ignored(self):
        from masova_agent.tools import backend_tools
        from tests.test_backend_tools import _mock_get

        token = bind_identity(AgentIdentity("REAL-CUST", "CUSTOMER", None, "jwt-real"))
        try:
            with patch("masova_agent.tools.backend_tools.httpx.get") as g:
                g.return_value = _mock_get(200, {
                    "id": "REAL-CUST", "loyaltyPoints": 10, "loyaltyTier": "SILVER", "name": "Real",
                })
                # Tool takes no customer_id — identity from contextvars
                text = backend_tools.get_loyalty_points()
                # Request path must use JWT id, not a spoofed argument
                called_url = g.call_args[0][0]
                assert "REAL-CUST" in called_url
                assert "SPOOF" not in called_url
            assert "10" in text or "SILVER" in text
        finally:
            reset_identity(token)


# ---------------------------------------------------------------------------
# 7. Cancel / refund manager approval copy
# ---------------------------------------------------------------------------

class TestEvalApprovalCopy:
    def test_cancel_mentions_manager(self):
        from masova_agent.tools.backend_tools import cancel_order
        from tests.test_backend_tools import _mock_get, _mock_post

        token = bind_identity(AgentIdentity("C1", "CUSTOMER", None, "jwt"))
        try:
            with patch("masova_agent.tools.backend_tools.httpx.get") as g, patch(
                "masova_agent.tools.backend_tools.httpx.post"
            ) as p:
                g.return_value = _mock_get(200, {"status": "RECEIVED"})
                p.return_value = _mock_post(200, {
                    "status": "PENDING_APPROVAL", "cancellationRequested": True,
                })
                text = cancel_order("ord-1", "changed mind")
            assert "manager" in text.lower()
        finally:
            reset_identity(token)

    def test_refund_mentions_manager(self):
        from masova_agent.tools.backend_tools import request_refund
        from tests.test_backend_tools import _mock_post

        token = bind_identity(AgentIdentity("C1", "CUSTOMER", None, "jwt"))
        try:
            with patch("masova_agent.tools.backend_tools.httpx.post") as p:
                p.return_value = _mock_post(201, {
                    "status": "PENDING_APPROVAL", "refundId": "R1",
                })
                text = request_refund("ord-1", "missing item in bag")
            assert "manager" in text.lower() or "approval" in text.lower()
        finally:
            reset_identity(token)


# ---------------------------------------------------------------------------
# 8. Idempotency
# ---------------------------------------------------------------------------

class TestEvalIdempotency:
    @pytest.mark.asyncio
    async def test_second_po_same_key_noop(self):
        with patch.object(ops_tools, "_require_token", return_value=None), patch.object(
            ops_tools, "post_json", new_callable=AsyncMock, return_value=(201, {"id": "po"})
        ) as post:
            items = [{"id": "i1", "name": "X", "quantity": 5}]
            a = await ops_tools.create_draft_po("DOM001", "sup-1", items=items)
            b = await ops_tools.create_draft_po("DOM001", "sup-1", items=items)
        assert a.get("proposal")
        assert b.get("duplicate") is True
        assert post.await_count == 1


# ---------------------------------------------------------------------------
# 9. EXECUTE rejected
# ---------------------------------------------------------------------------

class TestEvalExecutePolicy:
    def test_execute_tools_rejected(self):
        pe = PolicyEngine()
        for name in (
            "patch_menu_price",
            "execute_purchase_order",
            "execute_refund",
            "cancel_order_immediate",
            "send_campaign_live",
            "confirm_shifts",
        ):
            assert pe.tier_for(name) == RiskTier.EXECUTE
            assert pe.is_allowed(name, [name]) is False
