"""
Agent 6: Shift Optimisation
Schedule: Sundays at 8pm IST (for coming week)
Input: Agent 2 demand forecast for next week + existing shifts + staff pool
Output: Draft shifts for the coming week (status=DRAFT) — manager reviews + confirms
Uses: GET /api/bi?type=demand-forecast, GET /api/users, POST /api/shifts/bulk
"""
import httpx
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Roles that count as kitchen/service staff for scheduling
SCHEDULABLE_ROLES = {"KITCHEN_STAFF", "CASHIER", "DRIVER"}

# Shift slots match seeded roster windows (store hours 09:00–22:00, evening to 23:00).
SHIFT_SLOTS = [
    {"name": "Morning", "startHour": 9, "endHour": 16},
    {"name": "Mid", "startHour": 11, "endHour": 19},
    {"name": "Evening", "startHour": 16, "endHour": 23},
]

# Forecast demand threshold to trigger an extra staff slot
HIGH_DEMAND_THRESHOLD = 15  # predicted orders/hour




SHIFT_INSTRUCTION = """You are MaSoVa Shift Optimisation Agent (ops).
Use read_staff_slots and get_forecast_snippet. Draft bulk shifts with create_draft_shifts
(status DRAFT only). Copy each employee's id, name, and role from read_staff_slots —
never invent names. Use only these windows: Morning 09:00-16:00, Mid 11:00-19:00,
Evening 16:00-23:00. notify_managers with rationale. Never confirm shifts as final.
"""


def _shift_llm_runner():
    from ..runtime.ops_llm import make_ops_llm_runner
    from ..runtime.wrap import AGENT_ALLOWLISTS

    return make_ops_llm_runner(
        instruction=SHIFT_INSTRUCTION,
        tool_names=list(AGENT_ALLOWLISTS["shift_optimisation"]),
    )


async def run_shift_optimisation(store_id: Optional[str] = None):
    """Public entry — LLM tool loop + rule fallback."""
    from ..runtime.wrap import run_ops_agent
    from ..runtime.ops_llm import ops_prefer_llm
    from ..services.demo_backend import demo_focus_store_id, demo_mode

    if not store_id and demo_mode():
        store_id = demo_focus_store_id()

    async def _fallback():
        return await _rule_run_shift_optimisation(scope_store_id=store_id)

    prefer = ops_prefer_llm()
    return await run_ops_agent(
        "shift_optimisation",
        "scheduled",
        _fallback,
        store_id=store_id,
        goal="Draft next week's shift roster from demand forecast",
        context={"store_id": store_id} if store_id else {},
        llm_runner=_shift_llm_runner() if prefer else None,
        prefer_llm=prefer,
    )

async def _rule_run_shift_optimisation(scope_store_id: Optional[str] = None) -> Dict[str, Any]:
    """Draft next week's shift schedule based on demand forecast."""
    from ..tools.ops_http import agent_token, post_json

    if not agent_token():
        logger.warning("AGENT_TOKEN not set — shift optimisation skipped")
        return {"error": "AGENT_TOKEN not configured"}

    shifts_drafted = 0
    stores_processed = 0
    drafted_rows: List[Dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        stores = await _get_stores(client)
        from ..tools.ops_http import focus_store_list
        from ..services.demo_backend import demo_focus_store_id, demo_mode
        scope = scope_store_id or (demo_focus_store_id() if demo_mode() else None)
        stores = focus_store_list(stores, scope)
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
            staff = await _get_staff(client, store_id)
            if not staff:
                continue

            # Get demand forecast for next week (7 days)
            forecast = await _get_weekly_forecast(client, store_id, week_start)

            # Build draft shifts
            draft_shifts = _build_draft_shifts(store_id, staff, forecast, week_start)
            if not draft_shifts:
                continue

            # POST bulk draft shifts
            status, body = await post_json(
                client,
                "/api/shifts/bulk",
                {"storeId": store_id, "shifts": draft_shifts, "status": "DRAFT"},
            )

            if status in (200, 201):
                shifts_drafted += len(draft_shifts)
                stores_processed += 1
                drafted_rows.extend(draft_shifts)
                await _notify_managers(
                    client, store_id,
                    f"Shift schedule for next week ({week_start.strftime('%d %b')} – "
                    f"{(week_start + timedelta(days=6)).strftime('%d %b')}) has been drafted "
                    f"({len(draft_shifts)} shifts). Please review and confirm."
                )
                logger.info("Drafted %d shifts for store %s", len(draft_shifts), store_id)
            else:
                logger.warning("Failed to post bulk shifts for store %s: %s", store_id, str(body)[:120])

    logger.info(
        "Shift Optimisation complete: %d shifts drafted across %d stores",
        shifts_drafted, stores_processed,
    )
    week_label = (
        f"{week_start.strftime('%d %b')} – {(week_start + timedelta(days=6)).strftime('%d %b')}"
    )
    proposals: List[Dict[str, Any]] = []
    if drafted_rows:
        from ..runtime.models import ActionProposal

        focus_id = (drafted_rows[0].get("storeId") or scope or "")
        line_items = _shift_line_items(drafted_rows)
        proposals.append(ActionProposal(
            type="DRAFT_SHIFT_ROSTER",
            store_id=str(focus_id),
            summary=f"Draft roster · {len(drafted_rows)} slots · {week_label}",
            rationale=(
                f"Next week ({week_label}) drafted from forecast demand and the store staff pool. "
                "Confirm to publish these DRAFT shifts."
            ),
            payload={
                "week_start": week_start.strftime("%Y-%m-%d"),
                "shift_count": len(drafted_rows),
                "items": line_items,
                "message": (
                    f"{len(drafted_rows)} draft slots for {week_label}. "
                    "Approve to confirm the roster."
                ),
            },
            evidence=[
                {
                    "tool": "create_draft_shifts",
                    "row_id": str(focus_id),
                    "field": "shift_count",
                    "value": len(drafted_rows),
                }
            ],
            requires_approval=True,
            agent="shift_optimisation",
        ).to_dict())
    return {
        "status": "ok",
        "week_start": week_start.strftime("%Y-%m-%d"),
        "shifts_drafted": shifts_drafted,
        "stores_processed": stores_processed,
        "proposals": proposals,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_stores(client) -> List[Dict]:
    from ..tools.ops_http import get_json, unwrap_list

    status, data = await get_json(client, "/api/stores")
    if status != 200:
        return []
    return unwrap_list(data)


async def _get_staff(client, store_id: str) -> List[Dict]:
    from ..tools.ops_http import get_json, unwrap_list

    status, data = await get_json(
        client,
        "/api/users",
        params={"storeId": store_id, "available": "true"},
    )
    if status != 200:
        return []
    all_users = unwrap_list(data)
    return [
        u for u in all_users
        if (u.get("type") or u.get("role") or "").upper() in SCHEDULABLE_ROLES
    ]


async def _get_weekly_forecast(
    client, store_id: str, week_start: datetime
) -> Dict[str, Any]:
    """
    Returns forecast keyed by day-of-week (0=Mon) → hour → predictedQty.
    Falls back to empty dict if unavailable.
    """
    from ..tools.ops_http import get_json

    status, raw = await get_json(
        client,
        "/api/bi",
        params={"storeId": store_id, "type": "demand-forecast", "horizonDays": 7},
    )
    if status != 200:
        return {}

    forecast: Dict[int, Dict[int, float]] = {}
    if isinstance(raw, list):
        items = raw
    else:
        items = raw.get("items") or raw.get("forecasts") or raw.get("points") or raw.get("content") or []

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

                role = employee.get("role") or employee.get("type") or "KITCHEN_STAFF"
                name = employee.get("name") or employee.get("fullName") or employee["id"]
                start_hh = f"{slot['startHour']:02d}:00"
                end_hh = "00:00" if slot["endHour"] == 24 else f"{slot['endHour']:02d}:00"
                date_str = day.strftime("%Y-%m-%d")
                draft_shifts.append({
                    "storeId": store_id,
                    "employeeId": employee["id"],
                    "userId": employee["id"],
                    "staffId": employee["id"],
                    "name": name,
                    "role": role,
                    "date": date_str,
                    "startTime": start_hh,
                    "endTime": end_hh,
                    "startAt": shift_start.isoformat(),
                    "endAt": shift_end.isoformat(),
                    "status": "DRAFT",
                    "slotName": slot["name"],
                    "autoGenerated": True,
                    "note": f"Auto-drafted by Shift Optimisation Agent (demand: {slot_demand:.0f})",
                })

    return draft_shifts


def _role_label(role: str) -> str:
    return (role or "STAFF").replace("_", " ").title()


def _hhmm(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "T" in raw:
        return raw.split("T", 1)[1][:5]
    return raw[:5] if len(raw) >= 4 else raw


def _shift_line_items(shifts: List[Dict]) -> List[Dict]:
    rows: List[Dict] = []
    for s in shifts:
        name = s.get("name") or s.get("staffName") or s.get("staff_name") or "Staff"
        role = s.get("role") or s.get("type") or "STAFF"
        date = str(s.get("date") or "")[:10]
        start = _hhmm(s.get("startTime") or s.get("start_time") or s.get("startAt"))
        end = _hhmm(s.get("endTime") or s.get("end_time") or s.get("endAt"))
        slot = str(s.get("slotName") or s.get("slot") or "")
        window = " · ".join(p for p in (date, f"{start}–{end}" if start and end else "", slot) if p)
        rows.append({
            "itemName": f"{name} · {_role_label(role)}",
            "staffName": name,
            "role": role,
            "date": date,
            "startTime": start,
            "endTime": end,
            "slotName": slot,
            "window": window,
        })
    return rows


async def _notify_managers(client, store_id, message):
    from ..tools.ops_http import get_json, post_json, unwrap_list

    status, managers = await get_json(
        client,
        "/api/users",
        params={"type": "MANAGER", "storeId": store_id},
    )
    if status != 200:
        return
    for manager in unwrap_list(managers):
        await post_json(
            client,
            "/api/notifications",
            {
                "userId": manager["id"],
                "type": "SHIFT_DRAFT_READY",
                "title": "Next Week's Shifts Drafted",
                "message": message,
                "priority": "MEDIUM",
            },
        )
