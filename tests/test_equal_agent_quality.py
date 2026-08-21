"""
Equal industry-quality bar across agents 1–8.

Covers: allowlist/EXECUTE policy, fallback when LLM fails, WMA as compute source,
pricing never PATCHes menu, idempotency on propose tools, audit fields, runtime entry.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from masova_agent.runtime.idempotency import clear_for_tests, make_key, check_or_claim
from masova_agent.runtime.wrap import AGENT_ALLOWLISTS
from masova_agent.runtime.policy import DEFAULT_TOOL_REGISTRY, PolicyEngine, RiskTier
from masova_agent.runtime.agent_runtime import get_runtime, reset_runtime_for_tests
from masova_agent.runtime.models import AgentRunRequest


@pytest.fixture(autouse=True)
def _clean():
    clear_for_tests()
    reset_runtime_for_tests()
    yield
    clear_for_tests()
    reset_runtime_for_tests()


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    monkeypatch.setenv("OPS_PREFER_LLM", "false")
    monkeypatch.delenv("LLM_API_KEY", raising=False)


# ---------------------------------------------------------------------------
# Shared bar: tools / EXECUTE
# ---------------------------------------------------------------------------

class TestEqualToolPolicy:
    def test_all_ops_agents_have_allowlists(self):
        for name in (
            "demand_forecast",
            "inventory_reorder",
            "churn_prevention",
            "review_response",
            "shift_optimisation",
            "kitchen_coach",
            "dynamic_pricing",
            "support_chat",
        ):
            assert name in AGENT_ALLOWLISTS
            assert len(AGENT_ALLOWLISTS[name]) >= 2

    def test_no_execute_on_any_allowlist(self):
        pe = PolicyEngine()
        for agent, tools in AGENT_ALLOWLISTS.items():
            cleaned = pe.filter_allowlist(tools)
            for t in cleaned:
                assert pe.tier_for(t) != RiskTier.EXECUTE, f"{agent} has EXECUTE {t}"
            assert "patch_menu_price" not in tools

    def test_execute_rejected_if_requested(self):
        pe = PolicyEngine()
        assert pe.is_allowed("patch_menu_price", ["patch_menu_price"]) is False
        assert pe.is_allowed("execute_refund", ["execute_refund"]) is False


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_second_claim_is_duplicate(self):
        key = make_key("inventory_reorder", "DOM001", "draft_po", window="hour", extra="sup-1")
        ok1, _ = check_or_claim(key, {"n": 1})
        ok2, prior = check_or_claim(key, {"n": 2})
        assert ok1 is True
        assert ok2 is False
        assert prior.get("n") == 1

    @pytest.mark.asyncio
    async def test_create_draft_po_skips_duplicate(self):
        from masova_agent.tools import ops_tools

        with patch.object(ops_tools, "_require_token", return_value=None), patch.object(
            ops_tools, "post_json", new_callable=AsyncMock, return_value=(201, {"id": "po-1"})
        ) as post:
            items = [{"id": "inv-1", "name": "Flour", "quantity": 10, "unitCost": 1}]
            r1 = await ops_tools.create_draft_po("DOM001", "sup-1", items=items)
            r2 = await ops_tools.create_draft_po("DOM001", "sup-1", items=items)
        assert r1.get("ok") is True and r1.get("proposal")
        assert r2.get("duplicate") is True
        assert post.await_count == 1

    @pytest.mark.asyncio
    async def test_create_draft_campaign_idempotent(self):
        from masova_agent.tools import ops_tools

        with patch.object(ops_tools, "_require_token", return_value=None), patch.object(
            ops_tools, "post_json", new_callable=AsyncMock, return_value=(201, {"id": "c1"})
        ) as post:
            r1 = await ops_tools.create_draft_campaign(
                "DOM001", customer_ids=["a", "b"], message="hi"
            )
            r2 = await ops_tools.create_draft_campaign(
                "DOM001", customer_ids=["a", "b"], message="hi"
            )
        assert r1.get("proposal")
        assert r2.get("duplicate") is True
        assert post.await_count == 1


# ---------------------------------------------------------------------------
# Agent 2 demand — WMA source of truth
# ---------------------------------------------------------------------------

class TestDemandEqualBar:
    @pytest.mark.asyncio
    async def test_wma_is_compute_source(self):
        from masova_agent.tools.ops_tools import compute_wma_forecast

        r = await compute_wma_forecast(series=[10, 20, 30])
        assert r["ok"] is True
        assert r["forecast"] == pytest.approx(round((10 * 1 + 20 * 2 + 30 * 3) / 6, 4))
        assert "method" in r

    @pytest.mark.asyncio
    async def test_fallback_when_llm_raises(self):
        from masova_agent.runtime.wrap import run_ops_agent

        async def boom(_req):
            raise RuntimeError("llm down")

        async def fb():
            return {"status": "ok", "forecasts": 3, "stores": 1, "summary": "rule forecast"}

        with patch("masova_agent.runtime.ops_llm.ops_prefer_llm", return_value=True):
            result = await run_ops_agent(
                "demand_forecast",
                "manual",
                fb,
                llm_runner=boom,
                prefer_llm=True,
            )
        assert result.get("status") == "ok" or result.get("forecasts") == 3
        assert result["_runtime"]["used_fallback"] is True

    @pytest.mark.asyncio
    async def test_runtime_audit_has_tools_and_fallback(self):
        runtime = get_runtime()

        async def fb():
            return {"status": "ok", "summary": "demand done", "tools_used": ["compute_wma_forecast"]}

        res = await runtime.run(
            AgentRunRequest(
                agent_name="demand_forecast",
                trigger_type="manual",
                prefer_llm=False,
                fallback=fb,
                allowed_tools=list(AGENT_ALLOWLISTS["demand_forecast"]),
            )
        )
        assert res.used_fallback is True
        assert "compute_wma_forecast" in res.tools_used
        rec = runtime.audit.records[-1]
        assert rec["agent"] == "demand_forecast"
        assert rec["used_fallback"] is True


# ---------------------------------------------------------------------------
# Agents 3–7 golden scenarios
# ---------------------------------------------------------------------------

class TestInventoryEqualBar:
    @pytest.mark.asyncio
    async def test_no_token_rule_path_errors_cleanly(self):
        from masova_agent.agents.inventory_reorder_agent import run_inventory_reorder

        cfg = MagicMock(backend_url="http://test", agent_token="", google_api_key="")
        with patch("masova_agent.utils.config.get_config", return_value=cfg):
            result = await run_inventory_reorder()
        assert "error" in result or result.get("_runtime", {}).get("status")


class TestChurnEqualBar:
    @pytest.mark.asyncio
    async def test_empty_segment_no_campaign(self):
        from masova_agent.agents.churn_prevention_agent import run_churn_prevention

        client = AsyncMock()
        client.get = AsyncMock(side_effect=[
            MagicMock(status_code=200, json=lambda: [{"id": "s1"}], text="[]"),
            MagicMock(status_code=200, json=lambda: {"content": []}, text="{}"),
        ])
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=client)
        ctx.__aexit__ = AsyncMock(return_value=False)
        cfg = MagicMock(backend_url="http://test", agent_token="tok", google_api_key="k")
        with patch("masova_agent.utils.config.get_config", return_value=cfg), patch(
            "masova_agent.agents.churn_prevention_agent.httpx.AsyncClient", return_value=ctx
        ):
            result = await run_churn_prevention()
        assert result.get("campaigns_created", 0) == 0


class TestReviewEqualBar:
    @pytest.mark.asyncio
    async def test_high_rating_skip_signal_gate(self):
        from masova_agent.agents.review_response_agent import draft_review_response

        result = await draft_review_response(
            {"reviewId": "r1", "rating": 5, "text": "Great", "storeId": "s1"}
        )
        assert result.get("skipped") is True


class TestShiftEqualBar:
    def test_drafts_are_draft_status(self):
        from masova_agent.agents.shift_optimisation_agent import _build_draft_shifts
        from datetime import datetime

        shifts = _build_draft_shifts(
            "s1",
            [{"id": "e1", "type": "KITCHEN_STAFF"}],
            {},
            datetime(2026, 8, 1),
        )
        assert all(s["status"] == "DRAFT" for s in shifts)
        assert len(shifts) >= 7


class TestKitchenEqualBar:
    def test_brief_uses_metric_numbers(self):
        from masova_agent.agents.kitchen_coach_agent import _build_brief

        brief = _build_brief("Store", {
            "ticket_count": 99, "avg_prep_minutes": 12, "completed": 90, "cancelled": 1,
        })
        assert "99" in brief and "12" in brief


# ---------------------------------------------------------------------------
# Agent 8 pricing — never menu PATCH
# ---------------------------------------------------------------------------

class TestPricingEqualBar:
    def test_allowlist_has_no_patch(self):
        tools = AGENT_ALLOWLISTS["dynamic_pricing"]
        assert "patch_menu_price" not in tools
        for t in tools:
            assert "patch" not in t.lower() or "menu" not in t.lower()

    @pytest.mark.asyncio
    async def test_propose_price_never_calls_menu_patch(self):
        from masova_agent.tools import ops_tools

        posts = []

        async def capture_post(client, path, body=None):
            posts.append(path)
            return 201, {"id": "n1"}

        async def managers(client, path, params=None):
            return 200, {"content": [{"id": "mgr-1"}]}

        with patch.object(ops_tools, "_require_token", return_value=None), patch.object(
            ops_tools, "get_json", side_effect=managers
        ), patch.object(ops_tools, "post_json", side_effect=capture_post):
            r = await ops_tools.propose_price_suggestion(
                store_id="DOM001",
                direction="increase",
                percent=12,
                item_names=["Pizza"],
                active_count=20,
            )
        assert r.get("patches_menu") is False
        assert all("/api/menu" not in p for p in posts)
        assert any("/api/notifications" in p for p in posts)

    @pytest.mark.asyncio
    async def test_pre_gate_skip_when_no_signal(self):
        from masova_agent.agents.dynamic_pricing_agent import _pricing_pre_gate
        from masova_agent.runtime.models import AgentRunRequest

        req = AgentRunRequest(
            agent_name="dynamic_pricing",
            trigger_type="manual",
            context={"pricing_signal": "none"},
        )
        out = await _pricing_pre_gate(req)
        assert out is not None
        assert out.get("skipped_llm") is True
        assert out.get("suggestions_sent", 0) == 0


# ---------------------------------------------------------------------------
# Chat bar regression
# ---------------------------------------------------------------------------

class TestChatEqualBar:
    def test_chat_allowlist_identity_tools(self):
        tools = set(AGENT_ALLOWLISTS["support_chat"])
        assert "get_loyalty_points" in tools
        assert "cancel_order" in tools
        assert "request_refund" in tools
        assert "place_order" not in tools

    def test_max_tool_calls_on_policy(self):
        pe = PolicyEngine()
        assert pe.max_tool_calls == 12
