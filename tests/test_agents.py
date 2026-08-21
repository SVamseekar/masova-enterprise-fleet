"""
Unit tests for background agents 2–8.
All HTTP calls are mocked — no live backend required.

Patch strategy:
- get_config is imported lazily inside each agent function, so we patch
  masova_agent.utils.config.get_config (the source), not the agent module.
- httpx.AsyncClient is patched at the agent module level where it's imported.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime


@pytest.fixture(autouse=True)
def _disable_ops_llm(monkeypatch):
    """Agent unit tests exercise rule fallbacks only (no live LLM)."""
    monkeypatch.setenv("OPS_PREFER_LLM", "false")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    # Keep GOOGLE_API_KEY if present for review agent config mocks; prefer flag off is enough.


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _resp(status: int, body):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body
    r.text = str(body)[:120]
    return r


def _stores():
    return [{"id": "store-1", "name": "MaSoVa Jubilee Hills"}]


def _managers():
    return [{"id": "mgr-1", "name": "Test Manager"}]


def _mock_config():
    return MagicMock(backend_url="http://test", agent_token="tok", google_api_key="key")


def _async_client_ctx(client):
    """Return a context manager mock that yields `client`."""
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


# ---------------------------------------------------------------------------
# Agent 2: Demand Forecasting
# ---------------------------------------------------------------------------

class TestDemandForecastingAgent:
    @pytest.mark.asyncio
    async def test_successful_forecast_returns_summary(self):
        from masova_agent.agents.demand_forecasting_agent import run_demand_forecast

        orders = [
            {"createdAt": "2026-01-01T12:00:00Z",
             "items": [{"menuItemId": "item-1", "quantity": 3}]}
        ] * 5

        client = AsyncMock()
        client.get = AsyncMock(side_effect=[
            _resp(200, _stores()),
            _resp(200, {"content": orders}),
        ])
        client.post = AsyncMock(return_value=_resp(201, {}))

        with patch("masova_agent.utils.config.get_config", return_value=_mock_config()), \
             patch("masova_agent.agents.demand_forecasting_agent.httpx.AsyncClient",
                   return_value=_async_client_ctx(client)):
            result = await run_demand_forecast()

        assert "stores" in result or "forecasts" in result

    @pytest.mark.asyncio
    async def test_no_stores_returns_empty_result(self):
        from masova_agent.agents.demand_forecasting_agent import run_demand_forecast

        client = AsyncMock()
        client.get = AsyncMock(return_value=_resp(200, []))

        with patch("masova_agent.utils.config.get_config", return_value=_mock_config()), \
             patch("masova_agent.agents.demand_forecasting_agent.httpx.AsyncClient",
                   return_value=_async_client_ctx(client)):
            result = await run_demand_forecast()

        assert result.get("stores", 0) == 0 or "error" in result


# ---------------------------------------------------------------------------
# Agent 3: Inventory Reorder
# ---------------------------------------------------------------------------

class TestInventoryReorderAgent:
    @pytest.mark.asyncio
    async def test_drafts_pos_for_low_stock_items(self):
        from masova_agent.agents.inventory_reorder_agent import run_inventory_reorder

        low_stock = [{"id": "inv-1", "itemName": "Tomatoes",
                      "preferredSupplierId": "sup-1",
                      "reorderQuantity": 20, "unitCost": 50}]

        client = AsyncMock()
        client.get = AsyncMock(side_effect=[
            _resp(200, _stores()),
            _resp(200, {"content": low_stock}),
            _resp(200, {"content": _managers()}),
        ])
        client.post = AsyncMock(return_value=_resp(201, {"id": "PO-1"}))

        with patch("masova_agent.utils.config.get_config", return_value=_mock_config()), \
             patch("masova_agent.agents.inventory_reorder_agent.httpx.AsyncClient",
                   return_value=_async_client_ctx(client)):
            result = await run_inventory_reorder()

        assert result.get("pos_drafted", 0) >= 1

    @pytest.mark.asyncio
    async def test_no_low_stock_drafts_nothing(self):
        from masova_agent.agents.inventory_reorder_agent import run_inventory_reorder

        client = AsyncMock()
        client.get = AsyncMock(side_effect=[
            _resp(200, _stores()),
            _resp(200, {"content": []}),
        ])

        with patch("masova_agent.utils.config.get_config", return_value=_mock_config()), \
             patch("masova_agent.agents.inventory_reorder_agent.httpx.AsyncClient",
                   return_value=_async_client_ctx(client)):
            result = await run_inventory_reorder()

        assert result.get("pos_drafted", 0) == 0


# ---------------------------------------------------------------------------
# Agent 4: Churn Prevention
# ---------------------------------------------------------------------------

class TestChurnPreventionAgent:
    @pytest.mark.asyncio
    async def test_creates_campaign_for_churned_customers(self):
        from masova_agent.agents.churn_prevention_agent import run_churn_prevention

        churned = [{"id": "cust-1", "lastOrderDate": "2026-01-01T00:00:00Z",
                    "totalOrders": 5}]

        client = AsyncMock()
        client.get = AsyncMock(side_effect=[
            _resp(200, _stores()),
            _resp(200, {"content": churned}),
            _resp(200, []),                           # top items
            _resp(200, {"content": _managers()}),
        ])
        client.post = AsyncMock(return_value=_resp(201, {"id": "CMP-1"}))

        with patch("masova_agent.utils.config.get_config", return_value=_mock_config()), \
             patch("masova_agent.agents.churn_prevention_agent.httpx.AsyncClient",
                   return_value=_async_client_ctx(client)):
            result = await run_churn_prevention()

        assert result.get("campaigns_created", 0) >= 1
        assert result.get("customers_targeted", 0) >= 1

    @pytest.mark.asyncio
    async def test_no_churned_customers_creates_no_campaigns(self):
        from masova_agent.agents.churn_prevention_agent import run_churn_prevention

        client = AsyncMock()
        client.get = AsyncMock(side_effect=[
            _resp(200, _stores()),
            _resp(200, {"content": []}),
        ])

        with patch("masova_agent.utils.config.get_config", return_value=_mock_config()), \
             patch("masova_agent.agents.churn_prevention_agent.httpx.AsyncClient",
                   return_value=_async_client_ctx(client)):
            result = await run_churn_prevention()

        assert result.get("campaigns_created", 0) == 0


# ---------------------------------------------------------------------------
# Agent 5: Smart Review Response
# ---------------------------------------------------------------------------

class TestReviewResponseAgent:
    @pytest.mark.asyncio
    async def test_low_rating_generates_draft(self):
        from masova_agent.agents.review_response_agent import draft_review_response

        review = {"reviewId": "rev-1", "rating": 2,
                  "text": "Food was cold and arrived very late",
                  "storeId": "store-1", "orderId": "ORD-001"}

        client = AsyncMock()
        client.get = AsyncMock(side_effect=[
            _resp(200, {"items": [{"name": "Biryani"}]}),
            _resp(200, {"content": _managers()}),
        ])
        client.post = AsyncMock(return_value=_resp(201, {}))

        mock_genai_instance = MagicMock()
        mock_genai_instance.models.generate_content.return_value = MagicMock(
            text="We sincerely apologise for the experience."
        )

        with patch("masova_agent.utils.config.get_config", return_value=_mock_config()), \
             patch("masova_agent.agents.review_response_agent.httpx.AsyncClient",
                   return_value=_async_client_ctx(client)), \
             patch("google.genai.Client", return_value=mock_genai_instance):
            result = await draft_review_response(review)

        assert result.get("draftGenerated") is True
        assert result.get("reviewId") == "rev-1"

    @pytest.mark.asyncio
    async def test_high_rating_is_skipped(self):
        from masova_agent.agents.review_response_agent import draft_review_response

        result = await draft_review_response(
            {"reviewId": "rev-2", "rating": 5, "text": "Amazing!", "storeId": "store-1"}
        )
        assert result.get("skipped") is True


# ---------------------------------------------------------------------------
# Agent 6: Shift Optimisation
# ---------------------------------------------------------------------------

class TestShiftOptimisationAgent:
    @pytest.mark.asyncio
    async def test_drafts_shifts_for_store(self):
        from masova_agent.agents.shift_optimisation_agent import run_shift_optimisation

        staff = [{"id": "emp-1", "type": "KITCHEN_STAFF"},
                 {"id": "emp-2", "type": "CASHIER"}]

        client = AsyncMock()
        client.get = AsyncMock(side_effect=[
            _resp(200, _stores()),
            _resp(200, {"content": staff}),
            _resp(200, {}),                           # forecast
            _resp(200, {"content": _managers()}),
        ])
        client.post = AsyncMock(return_value=_resp(201, {}))

        with patch("masova_agent.utils.config.get_config", return_value=_mock_config()), \
             patch("masova_agent.agents.shift_optimisation_agent.httpx.AsyncClient",
                   return_value=_async_client_ctx(client)):
            result = await run_shift_optimisation()

        assert result.get("shifts_drafted", 0) > 0
        assert result.get("status") == "ok"

    @pytest.mark.asyncio
    async def test_no_stores_returns_no_stores(self):
        from masova_agent.agents.shift_optimisation_agent import run_shift_optimisation

        client = AsyncMock()
        client.get = AsyncMock(return_value=_resp(200, []))

        with patch("masova_agent.utils.config.get_config", return_value=_mock_config()), \
             patch("masova_agent.agents.shift_optimisation_agent.httpx.AsyncClient",
                   return_value=_async_client_ctx(client)):
            result = await run_shift_optimisation()

        assert result.get("status") == "no_stores"

    def test_build_draft_shifts_produces_21_slots_minimum(self):
        from masova_agent.agents.shift_optimisation_agent import _build_draft_shifts

        staff = [{"id": "emp-1", "type": "KITCHEN_STAFF"},
                 {"id": "emp-2", "type": "CASHIER"}]
        week_start = datetime(2026, 6, 1)
        shifts = _build_draft_shifts("store-1", staff, {}, week_start)

        # 7 days × 3 slots × 1 staff minimum (empty forecast = no high-demand)
        assert len(shifts) == 21
        assert all(s["status"] == "DRAFT" for s in shifts)
        assert all(s["storeId"] == "store-1" for s in shifts)


# ---------------------------------------------------------------------------
# Agent 7: Kitchen Coach
# ---------------------------------------------------------------------------

class TestKitchenCoachAgent:
    @pytest.mark.asyncio
    async def test_sends_brief_to_managers(self):
        from masova_agent.agents.kitchen_coach_agent import run_kitchen_coach

        metrics = {"totalOrders": 42, "completedOrders": 38,
                   "cancelledOrders": 2, "avgPrepTimeMinutes": 17}

        client = AsyncMock()
        client.get = AsyncMock(side_effect=[
            _resp(200, _stores()),
            _resp(200, metrics),
            _resp(200, {"content": _managers()}),
        ])
        client.post = AsyncMock(return_value=_resp(201, {}))

        with patch("masova_agent.utils.config.get_config", return_value=_mock_config()), \
             patch("masova_agent.agents.kitchen_coach_agent.httpx.AsyncClient",
                   return_value=_async_client_ctx(client)):
            result = await run_kitchen_coach()

        assert result.get("stores_processed") == 1
        assert result.get("notifications_sent") == 1

    def test_pick_tip_for_slow_prep(self):
        from masova_agent.agents.kitchen_coach_agent import _pick_tip, COACHING_TIPS
        tip = _pick_tip({"avg_prep_minutes": 25, "ticket_count": 30})
        assert tip in COACHING_TIPS["slow_prep"]

    def test_pick_tip_for_low_volume(self):
        from masova_agent.agents.kitchen_coach_agent import _pick_tip, COACHING_TIPS
        tip = _pick_tip({"avg_prep_minutes": 10, "ticket_count": 5})
        assert tip in COACHING_TIPS["low_ticket_volume"]

    def test_brief_contains_key_metrics(self):
        from masova_agent.agents.kitchen_coach_agent import _build_brief
        brief = _build_brief("Test Store", {
            "ticket_count": 50, "avg_prep_minutes": 18,
            "completed": 45, "cancelled": 2,
        })
        assert "50" in brief
        assert "45" in brief
        assert "18" in brief


# ---------------------------------------------------------------------------
# Agent 8: Dynamic Pricing
# ---------------------------------------------------------------------------

class TestDynamicPricingAgent:
    @pytest.mark.asyncio
    async def test_overload_triggers_price_increase_suggestion(self):
        from masova_agent.agents.dynamic_pricing_agent import run_dynamic_pricing
        from datetime import datetime as real_datetime

        top_items = [{"id": f"item-{i}", "name": f"Item {i}"} for i in range(5)]

        client = AsyncMock()
        client.get = AsyncMock(side_effect=[
            _resp(200, _stores()),
            _resp(200, {"totalElements": 20}),    # active orders — overloaded
            _resp(200, {"totalElements": 5}),     # recent 30min
            _resp(200, {"topItems": top_items}),  # top items
            _resp(200, {"content": _managers()}),
        ])
        client.post = AsyncMock(return_value=_resp(201, {}))

        fake_now = real_datetime(2026, 6, 1, 14, 0, 0)

        class FakeDatetime(real_datetime):
            @classmethod
            def now(cls, tz=None):
                return fake_now

        with patch("masova_agent.utils.config.get_config", return_value=_mock_config()), \
             patch("masova_agent.agents.dynamic_pricing_agent.httpx.AsyncClient",
                   return_value=_async_client_ctx(client)), \
             patch("masova_agent.agents.dynamic_pricing_agent.datetime", FakeDatetime):
            result = await run_dynamic_pricing()

        assert result.get("suggestions_sent", 0) >= 1

    @pytest.mark.asyncio
    async def test_slow_period_triggers_discount_suggestion(self):
        from masova_agent.agents.dynamic_pricing_agent import run_dynamic_pricing
        from datetime import datetime as real_datetime, timedelta

        slow_items = [{"id": f"item-{i}", "name": f"Dish {i}"} for i in range(6)]

        client = AsyncMock()
        client.get = AsyncMock(side_effect=[
            _resp(200, _stores()),
            _resp(200, {"totalElements": 2}),      # active — low
            _resp(200, {"totalElements": 1}),      # recent 30min — low
            _resp(200, {"content": slow_items}),   # menu items (all items)
            _resp(200, {"topItems": []}),           # analytics/products (no top items → all are slow)
            _resp(200, {"content": _managers()}),
        ])
        client.post = AsyncMock(return_value=_resp(201, {}))

        # Use a real datetime at 3pm so timedelta still works in the agent
        fake_now = real_datetime(2026, 6, 1, 15, 0, 0)

        class FakeDatetime(real_datetime):
            @classmethod
            def now(cls, tz=None):
                return fake_now

        with patch("masova_agent.utils.config.get_config", return_value=_mock_config()), \
             patch("masova_agent.agents.dynamic_pricing_agent.httpx.AsyncClient",
                   return_value=_async_client_ctx(client)), \
             patch("masova_agent.agents.dynamic_pricing_agent.datetime", FakeDatetime):
            result = await run_dynamic_pricing()

        assert result.get("suggestions_sent", 0) >= 1

    def test_overload_message_format(self):
        from masova_agent.agents.dynamic_pricing_agent import _overload_message
        msg = _overload_message("Test Store", 18,
                                [{"name": "Biryani"}, {"name": "Pizza"}], 12)
        assert "Biryani" in msg
        assert "12%" in msg
        assert "18" in msg

    def test_underload_message_format(self):
        from masova_agent.agents.dynamic_pricing_agent import _underload_message
        msg = _underload_message("Test Store", 1, [{"name": "Noodles"}], 15, 5)
        assert "Noodles" in msg
        assert "15%" in msg
