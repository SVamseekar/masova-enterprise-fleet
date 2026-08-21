"""
Agent 6: Shift Optimisation
Schedule: Sundays at 8pm IST (for coming week)
Input: Agent 2 demand forecast for next week + existing shifts + staff pool
Output: Draft shifts for the coming week (status=DRAFT) — manager reviews + confirms
Uses: GET /api/analytics/forecast, GET /api/users, GET /api/shifts, POST /api/shifts/bulk
"""
import httpx
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

# Roles that count as kitchen/service staff for scheduling
SCHEDULABLE_ROLES = {"KITCHEN_STAFF", "CASHIER", "DRIVER"}

# Shift slots (IST, 24h)
SHIFT_SLOTS = [
    {"name": "Morning", "startHour": 8, "endHour": 14},
    {"name": "Afternoon", "startHour": 14, "endHour": 20},
    {"name": "Evening", "startHour": 20, "endHour": 24},
]

# Forecast demand threshold to trigger an extra staff slot
HIGH_DEMAND_THRESHOLD = 15  # predicted orders/hour




SHIFT_INSTRUCTION = """You are MaSoVa Shift Optimisation Agent (ops).
Use read_staff_slots and get_forecast_snippet. Draft bulk shifts with create_draft_shifts
(status DRAFT only). notify_managers with rationale. Never confirm shifts as final.
"""


def _shift_llm_runner():
    from ..runtime.ops_llm import make_ops_llm_runner
    from ..runtime.wrap import AGENT_ALLOWLISTS

    return make_ops_llm_runner(
        instruction=SHIFT_INSTRUCTION,
        tool_names=list(AGENT_ALLOWLISTS["shift_optimisation"]),
    )


async def run_shift_optimisation():
    """Public entry — LLM tool loop + rule fallback."""
    from ..runtime.wrap import run_ops_agent
    from ..runtime.ops_llm import ops_prefer_llm

    prefer = ops_prefer_llm()
    return await run_ops_agent(
        "shift_optimisation",
        "scheduled",
        _rule_run_shift_optimisation,
        goal="Draft next week's shift roster from demand forecast",
        llm_runner=_shift_llm_runner() if prefer else None,
        prefer_llm=prefer,
    )

async def _rule_run_shift_optimisation() -> Dict[str, Any]:
    """Draft next week's shift schedule based on demand forecast."""
    from ..utils.config import get_config
    config = get_config()
    backend_url = config.backend_url
    headers = {"Authorization": f"Bearer {config.agent_token}", "Content-Type": "application/json"}

    shifts_drafted = 0
    stores_processed = 0

    async with httpx.AsyncClient(timeout=30.0) as client:
        stores = await _get_stores(client, backend_url, headers)
        if not stores:
            logger.warning("Shift Optimisation: no stores found")
            return {"status": "no_stores", "shifts_drafted": 0}

        # Next week Monday→Sunday (always at least 1 day ahead)
        today = datetime.now()
        days_until_monday = (7 - today.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        week_start = today + timedelta(days=days_until_monday)

        for store in stores:
            store_id = store["id"]

            # Get available staff for this store
            staff = await _get_staff(client, backend_url, headers, store_id)
            if not staff:
                continue

            # Get demand forecast for next week (7 days)
            forecast = await _get_weekly_forecast(client, backend_url, headers, store_id, week_start)

            # Build draft shifts
            draft_shifts = _build_draft_shifts(store_id, staff, forecast, week_start)
            if not draft_shifts:
                continue

            # POST bulk draft shifts
            res = await client.post(
                f"{backend_url}/api/shifts/bulk",
                json=draft_shifts,
                headers=headers,
            )

            if res.status_code in (200, 201):
                shifts_drafted += len(draft_shifts)
                stores_processed += 1
                await _notify_managers(
                    client, backend_url, headers, store_id,
                    f"Shift schedule for next week ({week_start.strftime('%d %b')} – "
                    f"{(week_start + timedelta(days=6)).strftime('%d %b')}) has been drafted "
                    f"({len(draft_shifts)} shifts). Please review and confirm."
                )
                logger.info("Drafted %d shifts for store %s", len(draft_shifts), store_id)
            else:
                logger.warning("Failed to post bulk shifts for store %s: %s", store_id, res.text[:120])

    logger.info(
        "Shift Optimisation complete: %d shifts drafted across %d stores",
        shifts_drafted, stores_processed,
    )
    return {
        "status": "ok",
        "week_start": week_start.strftime("%Y-%m-%d"),
        "shifts_drafted": shifts_drafted,
        "stores_processed": stores_processed,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_stores(client, backend_url, headers) -> List[Dict]:
    res = await client.get(f"{backend_url}/api/stores", headers=headers)
    if res.status_code != 200:
        return []
    data = res.json()
    if isinstance(data, list):
        return data
    return data.get("content") or []


async def _get_staff(client, backend_url, headers, store_id: str) -> List[Dict]:
    res = await client.get(
        f"{backend_url}/api/users?storeId={store_id}&available=true",
        headers=headers,
    )
    if res.status_code != 200:
        return []
    from . import _unwrap
    all_users = _unwrap(res.json())
    return [u for u in all_users if u.get("type") in SCHEDULABLE_ROLES]


async def _get_weekly_forecast(
    client, backend_url, headers, store_id: str, week_start: datetime
) -> Dict[str, Any]:
    """
    Returns forecast keyed by day-of-week (0=Mon) → hour → predictedQty.
    Falls back to empty dict if unavailable.
    """
    res = await client.get(
        f"{backend_url}/api/analytics/forecast?type=demand&storeId={store_id}",
        headers=headers,
    )
    if res.status_code != 200:
        return {}

    raw = res.json()
    forecast: Dict[int, Dict[int, float]] = {}
    items = raw.get("items") or raw.get("forecasts") or (raw if isinstance(raw, list) else [])

    for entry in items:
        dow = entry.get("dayOfWeek", 0)
        hour = entry.get("hourSlot", 0)
        qty = entry.get("predictedQuantity", 0)
        if dow not in forecast:
            forecast[dow] = {}
        forecast[dow][hour] = forecast[dow].get(hour, 0) + qty

    return forecast


def _build_draft_shifts(
    store_id: str,
    staff: List[Dict],
    forecast: Dict,
    week_start: datetime,
) -> List[Dict]:
    """
    Assign staff to shift slots across the coming week.
    Distributes staff evenly; adds extra cover on high-demand slots.
    """
    if not staff:
        return []

    draft_shifts = []
    staff_cycle = list(staff)
    staff_index = 0

    for day_offset in range(7):
        day = week_start + timedelta(days=day_offset)
        dow = day.weekday()
        day_forecast = forecast.get(dow, {})

        for slot in SHIFT_SLOTS:
            # Sum predicted orders in this slot
            slot_demand = sum(
                day_forecast.get(h, 0)
                for h in range(slot["startHour"], slot["endHour"])
            )
            # Assign at least 1 staff; 2 if high demand
            staff_count = 2 if slot_demand >= HIGH_DEMAND_THRESHOLD else 1

            for _ in range(staff_count):
                employee = staff_cycle[staff_index % len(staff_cycle)]
                staff_index += 1

                shift_start = day.replace(
                    hour=slot["startHour"], minute=0, second=0, microsecond=0
                )
                shift_end = day.replace(
                    hour=slot["endHour"] % 24, minute=0, second=0, microsecond=0
                )
                if slot["endHour"] == 24:
                    shift_end = (day + timedelta(days=1)).replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )

                draft_shifts.append({
                    "storeId": store_id,
                    "employeeId": employee["id"],
                    "startTime": shift_start.isoformat(),
                    "endTime": shift_end.isoformat(),
                    "status": "DRAFT",
                    "slotName": slot["name"],
                    "autoGenerated": True,
                    "note": f"Auto-drafted by Shift Optimisation Agent (demand: {slot_demand:.0f})",
                })

    return draft_shifts


async def _notify_managers(client, backend_url, headers, store_id, message):
    managers_res = await client.get(
        f"{backend_url}/api/users?type=MANAGER&storeId={store_id}", headers=headers
    )
    if managers_res.status_code != 200:
        return
    from . import _unwrap
    for manager in _unwrap(managers_res.json()):
        await client.post(
            f"{backend_url}/api/notifications",
            json={
                "userId": manager["id"],
                "type": "SHIFT_DRAFT_READY",
                "title": "Next Week's Shifts Drafted",
                "message": message,
                "priority": "MEDIUM",
            },
            headers=headers,
        )
