"""Contract fixture sanity + tool parsing against fixture shapes."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from masova_agent.auth import AgentIdentity, bind_identity, reset_identity
from tests.fixtures.backend_contracts import (
    ACTIVE_ORDER_STATUSES,
    CANCELLABLE_STATUSES,
    ORDER_STATUSES,
    ORDER_STATUSES_CANONICAL,
    REQUIRED_INVENTORY_FIELDS,
    REQUIRED_MENU_ITEM_FIELDS,
    REQUIRED_NOTIFICATION_FIELDS,
    REQUIRED_ORDER_FIELDS,
    REQUIRED_PO_FIELDS,
    REQUIRED_STORE_FIELDS,
    SAMPLE_CAMPAIGN_DRAFT,
    SAMPLE_CANCEL_REQUEST_RESPONSE,
    SAMPLE_CUSTOMER,
    SAMPLE_DRAFT_PO,
    SAMPLE_FORECAST_SNIPPET,
    SAMPLE_INVENTORY_ITEM,
    SAMPLE_INVENTORY_PAGE,
    SAMPLE_MENU_ITEM,
    SAMPLE_MENU_LIST,
    SAMPLE_MENU_PAGE,
    SAMPLE_NOTIFICATION,
    SAMPLE_ORDER,
    SAMPLE_ORDER_READY,
    SAMPLE_PRODUCTS_ANALYTICS,
    SAMPLE_REFUND_RESPONSE,
    SAMPLE_SHIFT_BULK,
    SAMPLE_STORE_FLAT,
    SAMPLE_STORE_NESTED,
    SAMPLE_USERS_MANAGERS,
)


@pytest.fixture(autouse=True)
def _id():
    t = bind_identity(AgentIdentity("CUST-1", "CUSTOMER", None, "jwt"))
    yield
    reset_identity(t)


class TestContractFixtures:
    def test_canonical_statuses_match_shared_models(self):
        expected = {
            "RECEIVED",
            "PREPARING",
            "OVEN",
            "BAKED",
            "READY",
            "DISPATCHED",
            "OUT_FOR_DELIVERY",
            "DELIVERED",
            "SERVED",
            "COMPLETED",
            "CANCELLED",
        }
        assert ORDER_STATUSES_CANONICAL == expected

    def test_order_statuses_cover_cancellable(self):
        assert CANCELLABLE_STATUSES <= ORDER_STATUSES

    def test_pending_is_dual_tolerance_only(self):
        assert "PENDING" in ORDER_STATUSES
        assert "PENDING" not in ORDER_STATUSES_CANONICAL

    def test_ready_status_in_canonical(self):
        assert "READY" in ORDER_STATUSES_CANONICAL
        assert SAMPLE_ORDER_READY["status"] == "READY"

    def test_required_fields_present(self):
        assert REQUIRED_ORDER_FIELDS <= SAMPLE_ORDER.keys()
        assert REQUIRED_MENU_ITEM_FIELDS <= SAMPLE_MENU_ITEM.keys()
        assert REQUIRED_STORE_FIELDS <= SAMPLE_STORE_NESTED.keys()
        assert REQUIRED_INVENTORY_FIELDS <= SAMPLE_INVENTORY_ITEM.keys()
        assert REQUIRED_PO_FIELDS <= SAMPLE_DRAFT_PO.keys()
        assert REQUIRED_NOTIFICATION_FIELDS <= SAMPLE_NOTIFICATION.keys()

    def test_missing_required_order_fields_detected(self):
        bad = {"orderNumber": "x"}
        assert not (REQUIRED_ORDER_FIELDS <= bad.keys())

    def test_get_order_status_fixture(self):
        from masova_agent.tools.backend_tools import get_order_status
        from tests.test_backend_tools import _mock_get

        with patch("masova_agent.tools.backend_tools.httpx.get") as g:
            g.return_value = _mock_get(200, SAMPLE_ORDER)
            text = get_order_status("ord-abc")
        assert "Margherita" in text
        assert "kitchen" in text.lower() or "prepared" in text.lower() or "PREPARING" in text

    def test_get_order_status_ready_fixture(self):
        from masova_agent.tools.backend_tools import get_order_status
        from tests.test_backend_tools import _mock_get

        with patch("masova_agent.tools.backend_tools.httpx.get") as g:
            g.return_value = _mock_get(200, SAMPLE_ORDER_READY)
            text = get_order_status("ord-ready")
        # Unknown-to-map statuses fall through to "is currently READY"
        assert "READY" in text or "ready" in text.lower()

    def test_menu_page_fixture(self):
        from masova_agent.tools.backend_tools import get_menu_items
        from tests.test_backend_tools import _mock_get

        with patch("masova_agent.tools.backend_tools.httpx.get") as g:
            g.return_value = _mock_get(200, SAMPLE_MENU_PAGE)
            text = get_menu_items("DOM001")
        assert "Margherita" in text

    def test_menu_list_fixture(self):
        from masova_agent.tools.backend_tools import get_menu_items
        from tests.test_backend_tools import _mock_get

        with patch("masova_agent.tools.backend_tools.httpx.get") as g:
            g.return_value = _mock_get(200, SAMPLE_MENU_LIST)
            text = get_menu_items("DOM001")
        assert "Margherita" in text

    def test_store_shapes(self):
        from masova_agent.tools.backend_tools import get_store_hours
        from tests.test_backend_tools import _mock_get

        with patch("masova_agent.tools.backend_tools.httpx.get") as g:
            g.return_value = _mock_get(200, SAMPLE_STORE_NESTED)
            assert "ACTIVE" in get_store_hours("DOM001") or "09:00" in get_store_hours("DOM001")
            g.return_value = _mock_get(200, SAMPLE_STORE_FLAT)
            flat = get_store_hours("store-1")
            assert "OPEN" in flat or "09:00" in flat

    def test_customer_loyalty_fixture(self):
        from masova_agent.tools.backend_tools import get_loyalty_points
        from tests.test_backend_tools import _mock_get

        with patch("masova_agent.tools.backend_tools.httpx.get") as g:
            g.return_value = _mock_get(200, SAMPLE_CUSTOMER)
            text = get_loyalty_points()
        assert "3200" in text and "GOLD" in text

    def test_refund_pending_fixture(self):
        from masova_agent.tools.backend_tools import request_refund
        from tests.test_backend_tools import _mock_post

        with patch("masova_agent.tools.backend_tools.httpx.post") as p:
            p.return_value = _mock_post(201, SAMPLE_REFUND_RESPONSE)
            text = request_refund("ord-abc", "Wrong items delivered")
        assert "pending manager approval" in text.lower() or "manager" in text.lower()

    def test_cancel_pending_fixture(self):
        from masova_agent.tools.backend_tools import cancel_order
        from tests.test_backend_tools import _mock_get, _mock_post

        with patch("masova_agent.tools.backend_tools.httpx.get") as g, patch(
            "masova_agent.tools.backend_tools.httpx.post"
        ) as p:
            g.return_value = _mock_get(200, {"status": "RECEIVED"})
            p.return_value = _mock_post(200, SAMPLE_CANCEL_REQUEST_RESPONSE)
            text = cancel_order("ord-abc", "Changed my mind")
        assert "manager" in text.lower()

    def test_active_statuses_subset_of_accepted(self):
        assert ACTIVE_ORDER_STATUSES <= ORDER_STATUSES


class TestOpsContractFixtures:
    """Ops tools tolerate inventory / PO / campaign / notification fixtures."""

    @pytest.mark.asyncio
    async def test_list_low_stock_fixture(self):
        from masova_agent.tools import ops_tools

        async def fake_get(client, path, params=None):
            if path == "/api/inventory":
                return 200, SAMPLE_INVENTORY_PAGE
            if path == "/api/stores":
                return 200, [SAMPLE_STORE_NESTED]
            return 404, {}

        with patch.object(ops_tools, "get_json", side_effect=fake_get), patch.object(
            ops_tools, "_require_token", return_value=None
        ):
            result = await ops_tools.list_low_stock("DOM001")
        assert result.get("ok") is True
        assert result.get("count", 0) >= 1
        assert result["items"][0]["item_name"]

    @pytest.mark.asyncio
    async def test_create_draft_po_returns_proposal_shape(self):
        from masova_agent.tools import ops_tools

        with patch.object(ops_tools, "_require_token", return_value=None), patch.object(
            ops_tools, "post_json", new_callable=AsyncMock, return_value=(201, SAMPLE_DRAFT_PO)
        ):
            result = await ops_tools.create_draft_po(
                store_id="DOM001",
                supplier_id="sup-1",
                items=[SAMPLE_INVENTORY_ITEM],
                rationale="Below reorder level",
            )
        assert result["ok"] is True
        prop = result["proposal"]
        assert prop["type"] == "DRAFT_PURCHASE_ORDER"
        assert prop.get("requires_approval") is True
        assert prop.get("store_id") == "DOM001"
        assert "summary" in prop

    @pytest.mark.asyncio
    async def test_create_draft_po_rejects_empty_items(self):
        from masova_agent.tools import ops_tools

        with patch.object(ops_tools, "_require_token", return_value=None):
            result = await ops_tools.create_draft_po(
                store_id="DOM001", supplier_id="sup-1", items=[]
            )
        assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_create_draft_campaign_fixture(self):
        from masova_agent.tools import ops_tools

        with patch.object(ops_tools, "_require_token", return_value=None), patch.object(
            ops_tools, "post_json", new_callable=AsyncMock, return_value=(201, SAMPLE_CAMPAIGN_DRAFT)
        ):
            result = await ops_tools.create_draft_campaign(
                store_id="DOM001",
                name="Win-back",
                message="Come back",
                customer_ids=["cust-1", "cust-2"],
                rationale="Inactive 30d",
            )
        assert result.get("ok") is True
        assert result["proposal"]["requires_approval"] is True

    @pytest.mark.asyncio
    async def test_create_draft_shifts_fixture(self):
        from masova_agent.tools import ops_tools

        with patch.object(ops_tools, "_require_token", return_value=None), patch.object(
            ops_tools, "post_json", new_callable=AsyncMock, return_value=(201, SAMPLE_SHIFT_BULK)
        ):
            result = await ops_tools.create_draft_shifts(
                store_id="DOM001",
                shifts=SAMPLE_SHIFT_BULK["shifts"],
                rationale="Sunday forecast peak",
            )
        assert result.get("ok") is True
        assert result["proposal"]["requires_approval"] is True

    @pytest.mark.asyncio
    async def test_notify_managers_fixture(self):
        from masova_agent.tools import ops_tools

        async def fake_get(client, path, params=None):
            return 200, SAMPLE_USERS_MANAGERS

        async def fake_post(client, path, body=None):
            assert REQUIRED_NOTIFICATION_FIELDS <= set(body.keys()) or "title" in body
            return 201, SAMPLE_NOTIFICATION

        with patch.object(ops_tools, "_require_token", return_value=None), patch.object(
            ops_tools, "get_json", side_effect=fake_get
        ), patch.object(ops_tools, "post_json", side_effect=fake_post):
            result = await ops_tools.notify_managers(
                store_id="DOM001",
                message="Draft PO ready",
                title="Agent Alert",
                rationale="Low stock",
            )
        assert result.get("ok") is True or result.get("sent", 0) >= 1

    @pytest.mark.asyncio
    async def test_get_forecast_snippet_fixture(self):
        from masova_agent.tools import ops_tools

        with patch.object(ops_tools, "_require_token", return_value=None), patch.object(
            ops_tools, "get_json", new_callable=AsyncMock, return_value=(200, SAMPLE_FORECAST_SNIPPET)
        ):
            result = await ops_tools.get_forecast_snippet(store_id="DOM001")
        assert result.get("ok") is True or "points" in result or "forecast" in str(result)

    @pytest.mark.asyncio
    async def test_compute_wma_does_not_need_http(self):
        from masova_agent.tools.ops_tools import compute_wma_forecast

        result = await compute_wma_forecast(series=[10, 20, 30, 40])
        assert result["ok"] is True
        assert "forecast" in result
        assert result["method"] == "weighted_moving_average"

    def test_draft_po_status_is_draft(self):
        assert SAMPLE_DRAFT_PO["status"] == "DRAFT"

    def test_campaign_status_is_draft(self):
        assert SAMPLE_CAMPAIGN_DRAFT["status"] == "DRAFT"

    def test_products_analytics_shape(self):
        assert "content" in SAMPLE_PRODUCTS_ANALYTICS
        assert SAMPLE_PRODUCTS_ANALYTICS["content"][0]["name"]


class TestPolicyMatchesCapabilityMap:
    def test_execute_tools_registered_as_execute(self):
        from masova_agent.runtime.policy import DEFAULT_TOOL_REGISTRY, RiskTier

        for name in (
            "patch_menu_price",
            "execute_purchase_order",
            "execute_refund",
            "cancel_order_immediate",
            "send_campaign_live",
            "confirm_shifts",
        ):
            assert DEFAULT_TOOL_REGISTRY[name].tier == RiskTier.EXECUTE

    def test_chat_and_ops_core_tools_registered(self):
        from masova_agent.runtime.policy import DEFAULT_TOOL_REGISTRY

        for name in (
            "get_order_status",
            "cancel_order",
            "request_refund",
            "list_low_stock",
            "create_draft_po",
            "compute_wma_forecast",
            "propose_price_suggestion",
            "notify_managers",
        ):
            assert name in DEFAULT_TOOL_REGISTRY
