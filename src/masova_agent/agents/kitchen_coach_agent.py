"""
Agent 7: Kitchen Performance Coach
Schedule: Nightly at 11pm IST
Input: Today's kitchen metrics (avg prep time, ticket count, staff performance)
       via GET /api/analytics/orders and GET /api/orders/kitchen analytics endpoints
Output: Nightly brief pushed as notification to managers + kitchen staff
"""
import httpx
import logging
from datetime import datetime
from typing import Dict, Any, List

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
"""


def _kitchen_llm_runner():
    from ..runtime.ops_llm import make_ops_llm_runner
    from ..runtime.wrap import AGENT_ALLOWLISTS

    return make_ops_llm_runner(
        instruction=KITCHEN_INSTRUCTION,
        tool_names=list(AGENT_ALLOWLISTS["kitchen_coach"]),
    )


async def run_kitchen_coach():
    """Public entry — LLM tool loop + rule fallback."""
    from ..runtime.wrap import run_ops_agent
    from ..runtime.ops_llm import ops_prefer_llm

    prefer = ops_prefer_llm()
    return await run_ops_agent(
        "kitchen_coach",
        "scheduled",
        _rule_run_kitchen_coach,
        goal="Send nightly kitchen performance brief from metrics",
        llm_runner=_kitchen_llm_runner() if prefer else None,
        prefer_llm=prefer,
    )

async def _rule_run_kitchen_coach() -> Dict[str, Any]:
    """Generate nightly kitchen performance brief and push to managers."""
    from ..utils.config import get_config
    config = get_config()
    backend_url = config.backend_url
    headers = {"Authorization": f"Bearer {config.agent_token}", "Content-Type": "application/json"}

    stores_processed = 0
    notifications_sent = 0

    async with httpx.AsyncClient(timeout=30.0) as client:
        stores = await _get_stores(client, backend_url, headers)

        for store in stores:
            store_id = store["id"]
            metrics = await _get_today_metrics(client, backend_url, headers, store_id)

            if metrics is None:
                logger.warning("Kitchen Coach: no metrics for store %s", store_id)
                continue

            brief = _build_brief(store.get("name", store_id), metrics)
            tip = _pick_tip(metrics)
            full_message = f"{brief}\n\n💡 Tip: {tip}"

            # Notify managers
            count = await _notify_managers(
                client, backend_url, headers, store_id, full_message
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

async def _get_stores(client, backend_url, headers) -> List[Dict]:
    res = await client.get(f"{backend_url}/api/stores", headers=headers)
    if res.status_code != 200:
        return []
    data = res.json()
    if isinstance(data, list):
        return data
    return data.get("content") or []


async def _get_today_metrics(
    client, backend_url, headers, store_id: str
) -> Dict[str, Any] | None:
    """
    Fetch today's order analytics for a store.
    Returns a normalised dict or None if unavailable.
    """
    # Primary: analytics endpoint
    res = await client.get(
        f"{backend_url}/api/analytics/orders?storeId={store_id}&period=today",
        headers=headers,
    )
    if res.status_code == 200:
        raw = res.json()
        return {
            "ticket_count": raw.get("totalOrders", raw.get("ticketCount", 0)),
            "avg_prep_minutes": raw.get("avgPrepTimeMinutes", raw.get("avgPrepTime", 0)),
            "completed": raw.get("completedOrders", raw.get("completed", 0)),
            "cancelled": raw.get("cancelledOrders", raw.get("cancelled", 0)),
        }

    # Fallback: count today's orders from order list
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    res2 = await client.get(
        f"{backend_url}/api/orders?storeId={store_id}&from={today_start.isoformat()}",
        headers=headers,
    )
    if res2.status_code != 200:
        return None

    orders = res2.json()
    order_list = orders.get("content") or (orders if isinstance(orders, list) else [])
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


def _pick_tip(metrics: Dict) -> str:
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

    # Rotate by day-of-year so the tip changes daily
    return tips[datetime.now().timetuple().tm_yday % len(tips)]


async def _notify_managers(
    client, backend_url, headers, store_id: str, message: str
) -> int:
    managers_res = await client.get(
        f"{backend_url}/api/users?type=MANAGER&storeId={store_id}", headers=headers
    )
    if managers_res.status_code != 200:
        return 0

    from . import _unwrap
    count = 0
    for manager in _unwrap(managers_res.json()):
        res = await client.post(
            f"{backend_url}/api/notifications",
            json={
                "userId": manager["id"],
                "type": "KITCHEN_BRIEF",
                "title": "Nightly Kitchen Performance Brief",
                "message": message,
                "priority": "LOW",
            },
            headers=headers,
        )
        if res.status_code in (200, 201):
            count += 1
    return count
