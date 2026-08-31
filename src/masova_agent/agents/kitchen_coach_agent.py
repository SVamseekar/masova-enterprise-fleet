"""
Agent 7: Kitchen Performance Coach
Schedule: Nightly at 11pm IST
Input: Today's kitchen metrics (avg prep time, ticket count, staff performance)
       via GET /api/orders/analytics?type=kitchen-metrics
Output: Nightly brief pushed as notification to managers + kitchen staff
"""
import httpx
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Baseline prep time in minutes — alert if store avg exceeds this
PREP_TIME_ALERT_THRESHOLD_MINUTES = 20

# Tips keyed by the issue detected — rotated daily so staff don't see the same tip
COACHING_TIPS = {
    "slow_prep": [
        "Prep ingredients in parallel for the top 3 ordered items before the next rush.",
        "Group similar dishes and batch-prep sauces at shift start to cut handoff time.",
        "Pre-portion standard garnishes at the beginning of each slot to reduce plate time.",
    ],
    "high_ticket_volume": [
        "Assign a dedicated expeditor during peak hours to keep the pass clear.",
        "Use station rotation every 90 minutes to keep energy high during long rushes.",
        "Call ahead to the prep station 10 minutes before a surge — watch the order queue trend.",
    ],
    "low_ticket_volume": [
        "Use slow periods to deep-clean prep surfaces and restock mise en place.",
        "Cross-train a slower shift on a new station today.",
        "Review tomorrow's forecast and prep stocks now to get ahead of the next rush.",
    ],
    "good_performance": [
        "Great shift! Keep the momentum — remind the team to log any near-misses for tomorrow's briefing.",
        "Excellent throughput today. Share what worked with the opening shift tomorrow.",
        "Solid numbers. Consider rotating the highest-performer to mentor a trainee on tomorrow's shift.",
    ],
}




KITCHEN_INSTRUCTION = """You are MaSoVa Kitchen Performance Coach (ops).
Call read_kitchen_metrics, write a short brief from those numbers only,
then draft_kitchen_brief / notify_managers. Do not invent metrics.
If period_date is present, quote that date instead of saying "today".
"""


def _kitchen_llm_runner():
    from ..runtime.ops_llm import make_ops_llm_runner
    from ..runtime.wrap import AGENT_ALLOWLISTS

    return make_ops_llm_runner(
        instruction=KITCHEN_INSTRUCTION,
        tool_names=list(AGENT_ALLOWLISTS["kitchen_coach"]),
    )


async def run_kitchen_coach(store_id: Optional[str] = None):
    """Public entry — LLM tool loop + rule fallback."""
    from ..runtime.wrap import run_ops_agent
    from ..runtime.ops_llm import ops_prefer_llm
    from ..services.demo_backend import demo_focus_store_id, demo_mode

    if not store_id and demo_mode():
        store_id = demo_focus_store_id()

    async def _fallback():
        return await _rule_run_kitchen_coach(scope_store_id=store_id)

    prefer = ops_prefer_llm()
    return await run_ops_agent(
        "kitchen_coach",
        "scheduled",
        _fallback,
        store_id=store_id,
        goal="Send nightly kitchen performance brief from metrics",
        context={"store_id": store_id} if store_id else {},
        llm_runner=_kitchen_llm_runner() if prefer else None,
        prefer_llm=prefer,
    )

async def _rule_run_kitchen_coach(scope_store_id: Optional[str] = None) -> Dict[str, Any]:
    """Generate nightly kitchen performance brief and push to managers."""
    from ..tools.ops_http import agent_token

    if not agent_token():
        logger.warning("AGENT_TOKEN not set — kitchen coach skipped")
        return {"error": "AGENT_TOKEN not configured"}

    stores_processed = 0
    notifications_sent = 0

    async with httpx.AsyncClient(timeout=30.0) as client:
        stores = await _get_stores(client)
        from ..tools.ops_http import focus_store_list
        from ..services.demo_backend import demo_focus_store_id, demo_mode
        scope = scope_store_id or (demo_focus_store_id() if demo_mode() else None)
        stores = focus_store_list(stores, scope)

        for store in stores:
            store_id = store["id"]
            metrics = await _get_today_metrics(client, store_id)

            if metrics is None:
                logger.warning("Kitchen Coach: no metrics for store %s", store_id)
                continue

            brief = _build_brief(store.get("name", store_id), metrics)
            tip = _pick_tip(metrics, store_id)
            full_message = f"{brief}\n\n💡 Tip: {tip}"

            # Notify managers
            count = await _notify_managers(
                client, store_id, full_message
            )
            notifications_sent += count
            stores_processed += 1
            logger.info("Kitchen Coach brief sent for store %s: %d notifications", store_id, count)

    logger.info(
        "Kitchen Coach complete: %d stores, %d notifications sent",
        stores_processed, notifications_sent,
    )
    return {
        "status": "ok",
        "stores_processed": stores_processed,
        "notifications_sent": notifications_sent,
        "generated_at": datetime.now().isoformat(),
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


async def _get_today_metrics(
    client, store_id: str
) -> Dict[str, Any] | None:
    """
    Fetch today's order analytics for a store.
    Returns a normalised dict or None if unavailable.
    """
    from ..tools.ops_http import get_json, unwrap_list

    # Primary: analytics endpoint
    status, raw = await get_json(
        client,
        "/api/orders/analytics",
        params={"storeId": store_id, "period": "today", "type": "kitchen-metrics"},
    )
    if status == 200:
        return {
            "ticket_count": raw.get("totalOrders", raw.get("ticketCount", 0)),
            "avg_prep_minutes": raw.get("avgPrepTimeMinutes", raw.get("avgPrepTime", 0)),
            "completed": raw.get("completedOrders", raw.get("completed", 0)),
            "cancelled": raw.get("cancelledOrders", raw.get("cancelled", 0)),
        }

    # Fallback: count today's orders from order list
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    orders_status, orders = await get_json(
        client,
        "/api/orders",
        params={"storeId": store_id, "from": today_start.isoformat()},
    )
    if orders_status != 200:
        return None

    order_list = unwrap_list(orders)
    completed = [o for o in order_list if o.get("status") in ("DELIVERED", "COMPLETED", "SERVED")]
    cancelled = [o for o in order_list if o.get("status") == "CANCELLED"]

    return {
        "ticket_count": len(order_list),
        "avg_prep_minutes": 0,  # no timestamp data available via this fallback
        "completed": len(completed),
        "cancelled": len(cancelled),
    }


def _build_brief(store_name: str, metrics: Dict) -> str:
    ticket_count = metrics["ticket_count"]
    avg_prep = metrics["avg_prep_minutes"]
    completed = metrics["completed"]
    cancelled = metrics["cancelled"]
    completion_rate = round((completed / ticket_count * 100) if ticket_count else 0, 1)

    lines = [
        f"🍳 Kitchen Brief — {store_name} — {datetime.now().strftime('%d %b %Y')}",
        f"Orders today: {ticket_count} | Completed: {completed} ({completion_rate}%) | Cancelled: {cancelled}",
    ]
    if avg_prep:
        lines.append(f"Avg prep time: {avg_prep:.1f} min")
        if avg_prep > PREP_TIME_ALERT_THRESHOLD_MINUTES:
            lines.append(f"⚠️ Prep time exceeded {PREP_TIME_ALERT_THRESHOLD_MINUTES} min target.")

    return "\n".join(lines)


def _pick_tip(metrics: Dict, store_id: str = "") -> str:
    avg_prep = metrics["avg_prep_minutes"]
    ticket_count = metrics["ticket_count"]

    if avg_prep > PREP_TIME_ALERT_THRESHOLD_MINUTES:
        tips = COACHING_TIPS["slow_prep"]
    elif ticket_count > 60:
        tips = COACHING_TIPS["high_ticket_volume"]
    elif ticket_count < 15:
        tips = COACHING_TIPS["low_ticket_volume"]
    else:
        tips = COACHING_TIPS["good_performance"]

    # Rotate by day-of-year AND store, so stores in the same bucket on the
    # same day don't all receive the identical tip text.
    day_of_year = datetime.now().timetuple().tm_yday
    offset = sum(ord(c) for c in store_id) if store_id else 0
    return tips[(day_of_year + offset) % len(tips)]


async def _notify_managers(
    client, store_id: str, message: str
) -> int:
    from ..tools.ops_http import get_json, post_json, unwrap_list

    managers_status, managers = await get_json(
        client,
        "/api/users",
        params={"type": "MANAGER", "storeId": store_id},
    )
    if managers_status != 200:
        return 0

    count = 0
    for manager in unwrap_list(managers):
        status, _ = await post_json(
            client,
            "/api/notifications",
            {
                "userId": manager["id"],
                "type": "KITCHEN_BRIEF",
                "title": "Nightly Kitchen Performance Brief",
                "message": message,
                "priority": "LOW",
            },
        )
        if status in (200, 201):
            count += 1
    return count
