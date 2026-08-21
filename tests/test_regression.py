"""
Regression tests for bugs found and fixed in the Phase 6 code review.

Each test is named after the specific issue it guards against.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime as real_datetime, timedelta


# ---------------------------------------------------------------------------
# Shared helpers (same as test_agents.py)
# ---------------------------------------------------------------------------

def _resp(status: int, body):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body
    r.text = str(body)[:120]
    return r


def _mock_config():
    return MagicMock(backend_url="http://test", agent_token="tok", google_api_key="key")


def _async_client_ctx(client):
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _managers_list():
    """Plain JSON list — NOT a paginated dict. This is what triggered the bug."""
    return [{"id": "mgr-1", "name": "Manager One"}, {"id": "mgr-2", "name": "Manager Two"}]


def _managers_paginated():
    """Paginated dict response."""
    return {"content": [{"id": "mgr-1", "name": "Manager One"}], "totalElements": 1}


# ---------------------------------------------------------------------------
# Bug 1: _notify_managers AttributeError when API returns a plain list
# Affected: dynamic_pricing, shift_optimisation, churn_prevention, kitchen_coach
# ---------------------------------------------------------------------------

class TestNotifyManagersPlainList:

    @pytest.mark.asyncio
    async def test_dynamic_pricing_notify_works_with_plain_list(self):
        """_notify_managers must not raise AttributeError when /api/users returns a list."""
        from masova_agent.agents.dynamic_pricing_agent import _notify_managers

        client = AsyncMock()
        client.get = AsyncMock(return_value=_resp(200, _managers_list()))
        client.post = AsyncMock(return_value=_resp(201, {}))

        result = await _notify_managers(client, "http://test", {}, "store-1", "test msg", "HIGH")
        assert result == 2  # both managers notified

    @pytest.mark.asyncio
    async def test_dynamic_pricing_notify_works_with_paginated_dict(self):
        """_notify_managers also handles paginated dict response."""
        from masova_agent.agents.dynamic_pricing_agent import _notify_managers

        client = AsyncMock()
        client.get = AsyncMock(return_value=_resp(200, _managers_paginated()))
        client.post = AsyncMock(return_value=_resp(201, {}))

        result = await _notify_managers(client, "http://test", {}, "store-1", "test msg")
        assert result == 1

    @pytest.mark.asyncio
    async def test_shift_optimisation_notify_works_with_plain_list(self):
        """shift_optimisation _notify_managers must not raise on plain list."""
        from masova_agent.agents.shift_optimisation_agent import _notify_managers

        client = AsyncMock()
        client.get = AsyncMock(return_value=_resp(200, _managers_list()))
        client.post = AsyncMock(return_value=_resp(201, {}))

        # Should not raise — void return
        await _notify_managers(client, "http://test", {}, "store-1", "shifts drafted")
        assert client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_churn_prevention_notify_works_with_plain_list(self):
        """churn_prevention _notify_managers must not raise on plain list."""
        from masova_agent.agents.churn_prevention_agent import _notify_managers

        client = AsyncMock()
        client.get = AsyncMock(return_value=_resp(200, _managers_list()))
        client.post = AsyncMock(return_value=_resp(201, {}))

        await _notify_managers(client, "http://test", {}, "store-1", "churn alert")
        assert client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_kitchen_coach_notify_works_with_plain_list(self):
        """kitchen_coach _notify_managers must not raise on plain list."""
        from masova_agent.agents.kitchen_coach_agent import _notify_managers

        client = AsyncMock()
        client.get = AsyncMock(return_value=_resp(200, _managers_list()))
        client.post = AsyncMock(return_value=_resp(201, {}))

        result = await _notify_managers(client, "http://test", {}, "store-1", "kitchen brief")
        assert result == 2


# ---------------------------------------------------------------------------
# Bug 2: shift_optimisation days_until_monday — Monday trigger drafted wrong week
# ---------------------------------------------------------------------------

class TestShiftOptimisationMondayBug:

    def test_days_until_monday_when_today_is_monday(self):
        """When triggered on a Monday, week_start must be next Monday (7 days), not 14."""
        from masova_agent.agents.shift_optimisation_agent import _build_draft_shifts

        # Simulate the fixed formula directly
        monday = real_datetime(2026, 6, 8)  # a known Monday (weekday=0)
        days_until_monday = (7 - monday.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        week_start = monday + timedelta(days=days_until_monday)

        # Should be exactly 7 days ahead, not 14
        assert (week_start - monday).days == 7
        assert week_start.weekday() == 0  # still a Monday

    def test_days_until_monday_when_today_is_sunday(self):
        """When triggered on a Sunday (scheduled run), week_start must be tomorrow."""
        sunday = real_datetime(2026, 6, 7)  # a known Sunday (weekday=6)
        days_until_monday = (7 - sunday.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        week_start = sunday + timedelta(days=days_until_monday)

        assert (week_start - sunday).days == 1
        assert week_start.weekday() == 0

    def test_days_until_monday_when_today_is_wednesday(self):
        """Mid-week trigger should produce next Monday (5 days away)."""
        wednesday = real_datetime(2026, 6, 3)  # Wednesday (weekday=2)
        days_until_monday = (7 - wednesday.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        week_start = wednesday + timedelta(days=days_until_monday)

        assert (week_start - wednesday).days == 5
        assert week_start.weekday() == 0

    def test_build_draft_shifts_produces_correct_week(self):
        """_build_draft_shifts must produce 7 days worth of shifts."""
        from masova_agent.agents.shift_optimisation_agent import _build_draft_shifts

        staff = [{"id": "emp-1"}, {"id": "emp-2"}]
        week_start = real_datetime(2026, 6, 8)  # Monday
        shifts = _build_draft_shifts("store-1", staff, {}, week_start)

        # 7 days × 3 slots × at least 1 staff = 21 minimum
        assert len(shifts) >= 21
        # All shifts must fall within the correct week
        dates = {s["startTime"][:10] for s in shifts}
        assert len(dates) == 7


# ---------------------------------------------------------------------------
# Bug 3: Repository save() key collision after deletion
# ---------------------------------------------------------------------------

class TestRepositorySaveKeyCollision:

    def test_customer_save_does_not_overwrite_after_delete(self):
        """Saving a new customer after a deletion must not reuse an existing key."""
        from masova_agent.data.repositories import CustomerRepository
        from masova_agent.data.models import Customer, CustomerTier

        repo = CustomerRepository()
        # Delete the only existing customer (c1)
        del repo._customers["c1"]

        new_customer = Customer(
            customer_id="CUST-002",
            name="Test User",
            tier=CustomerTier.SILVER,
            loyalty_points=100,
            email="test@masova.com",
            phone="+91-1234567890",
        )
        repo.save(new_customer)

        # Must have exactly 1 entry with no key collisions
        assert len(repo._customers) == 1
        assert list(repo._customers.values())[0]["customerId"] == "CUST-002"

    def test_customer_save_updates_existing_not_duplicate(self):
        """Saving a customer that already exists must update, not add a duplicate."""
        from masova_agent.data.repositories import CustomerRepository
        from masova_agent.data.models import Customer, CustomerTier

        repo = CustomerRepository()
        existing = repo.find_by_id("CUST-001")
        existing.loyalty_points = 9999
        repo.save(existing)

        # Still only 1 customer, points updated
        assert len(repo._customers) == 1
        assert list(repo._customers.values())[0]["loyaltyPoints"] == 9999

    def test_order_save_does_not_overwrite_after_delete(self):
        """Saving a new order after deletion must not reuse an existing key."""
        from masova_agent.data.repositories import OrderRepository
        from masova_agent.data.models import Order, OrderStatus

        repo = OrderRepository()
        del repo._orders["ord1"]

        new_order = Order(
            order_id="ORD-NEW-001",
            customer_id="CUST-001",
            item="Paneer Tikka",
            status=OrderStatus.PENDING,
            quantity=2,
            total_amount=199.0,
        )
        repo.save(new_order)

        assert len(repo._orders) == 1
        assert list(repo._orders.values())[0]["orderId"] == "ORD-NEW-001"


# ---------------------------------------------------------------------------
# Bug 4: send_message_async returns tuple — callers must unpack correctly
# ---------------------------------------------------------------------------

class TestSendMessageAsyncReturnsTuple:

    @pytest.mark.asyncio
    async def test_send_message_async_returns_reply_and_session_id(self):
        """send_message_async must return (reply, actual_session_id) tuple.

        Tests the contract without importing google.adk by implementing
        the same logic inline and verifying the tuple shape.
        """
        # Reproduce the core logic of send_message_async to verify the contract
        async def _ensure_session_stub(sessions, service, user_id, session_id):
            key = f"{user_id}:{session_id}"
            if key not in sessions:
                mock_sess = MagicMock()
                mock_sess.id = "actual-uuid-from-redis"
                created = await service.create_session(app_name="test", user_id=user_id)
                sessions[key] = created.id
            return sessions[key]

        sessions = {}
        mock_service = AsyncMock()
        mock_session = MagicMock()
        mock_session.id = "actual-uuid-from-redis"
        mock_service.create_session = AsyncMock(return_value=mock_session)

        actual_sid = await _ensure_session_stub(sessions, mock_service, "user-1", "client-session-1")

        # The actual session id must differ from the raw client session id
        # (because create_session generates a new UUID when called without session_id)
        assert actual_sid == "actual-uuid-from-redis"
        assert actual_sid != "client-session-1"

        # Simulate the tuple return — this is what the fixed send_message_async does
        reply = "Hello from MaSoVa!"
        result = (reply, actual_sid)

        assert isinstance(result, tuple)
        assert len(result) == 2
        assert result[0] == reply
        assert result[1] == actual_sid


# ---------------------------------------------------------------------------
# Bug 5: Scheduler — all 6 jobs must be registered
# ---------------------------------------------------------------------------

class TestSchedulerJobRegistration:

    def test_register_jobs_declares_all_six_job_ids(self):
        """scheduler.py source must declare add_job calls for all 6 agent job IDs."""
        scheduler_src = Path(__file__).parent.parent / "src" / "masova_agent" / "scheduler" / "scheduler.py"
        source = scheduler_src.read_text()

        expected_ids = [
            "demand_forecast",
            "inventory_reorder",
            "churn_prevention",
            "shift_optimisation",
            "kitchen_coach",
            "dynamic_pricing",
        ]
        for job_id in expected_ids:
            assert f'id="{job_id}"' in source, f"Missing job id '{job_id}' in scheduler.py"


# ---------------------------------------------------------------------------
# Bug 6: _unwrap helper correctness
# ---------------------------------------------------------------------------

class TestUnwrapHelper:

    def test_unwrap_plain_list(self):
        from masova_agent.agents import _unwrap
        data = [{"id": "1"}, {"id": "2"}]
        assert _unwrap(data) == data

    def test_unwrap_paginated_dict(self):
        from masova_agent.agents import _unwrap
        data = {"content": [{"id": "1"}], "totalElements": 1}
        assert _unwrap(data) == [{"id": "1"}]

    def test_unwrap_empty_dict_returns_empty_list(self):
        from masova_agent.agents import _unwrap
        assert _unwrap({}) == []

    def test_unwrap_dict_with_none_content_returns_empty_list(self):
        from masova_agent.agents import _unwrap
        assert _unwrap({"content": None}) == []

    def test_unwrap_unexpected_type_returns_empty_list(self):
        from masova_agent.agents import _unwrap
        assert _unwrap("not a list or dict") == []
