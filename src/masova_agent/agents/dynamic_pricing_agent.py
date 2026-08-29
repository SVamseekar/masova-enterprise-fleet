"""
Agent 8: Dynamic Pricing Suggestions
Schedule: Every 30 minutes during 9am-10pm IST
Input: Active order count, demand trend (last 30 min), time-to-close, top products
Output: DRAFT price adjustment notification to manager — agent NEVER changes prices.
        Manager approves via one-tap → PATCH /api/menu/{id} is called by the frontend.

LLM path: only when overload/underload signal exists; tool loop proposes notifications.
Fallback: threshold messages (same caps).
"""
import httpx
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Thresholds
OVERLOAD_ACTIVE_ORDERS = 15       # > this → suggest price increase on top sellers
UNDERLOAD_ORDERS_30MIN = 3        # < this in last 30 min → suggest discount on slow items
PRICE_INCREASE_PCT = 12           # % increase suggestion for overloaded kitchen
PRICE_DISCOUNT_PCT = 15           # % discount suggestion for slow periods
STORE_CLOSE_HOUR = 22             # 10pm IST — don't suggest discounts if <2h to close
MIN_HOURS_BEFORE_CLOSE = 2

PRICING_INSTRUCTION = """You are MaSoVa Dynamic Pricing Agent (ops).

You SUGGEST temporary price adjustments only. You MUST NEVER patch menu prices
or call any execute/price-write tool (none are available).

Workflow when context.signal is overload or underload:
1. Use count_active_orders / count_recent_orders / compute_pricing_signal for numbers.
2. For overload: get_top_items then propose_price_suggestion(direction=increase, percent<=12).
3. For underload: get_slow_items then propose_price_suggestion(direction=discount, percent<=15).
4. Include rationale citing the tool counts.

If signal is none, do nothing.
Respect percent caps. Manager applies prices in the UI.
"""


async def _pricing_pre_gate(request):
    """Skip LLM when no store has overload/underload signal (cost control)."""
    from ..tools.ops_tools import compute_pricing_signal, list_stores

    # Tests can force signal via context
    forced = (request.context or {}).get("pricing_signal")
    if forced == "none":
        return {
            "status": "ok",
            "summary": "No pricing signal — skipped LLM",
            "stores_evaluated": 0,
            "suggestions_sent": 0,
            "skipped_llm": True,
            "tools_used": [],
            "proposals": [],
        }
    if forced in ("overload", "underload"):
        return None  # proceed to LLM / scripted plan

    # Fast path without full rule agent: check signals only
    try:
        stores_res = await list_stores()
        stores = stores_res.get("stores") or []
    except Exception:
        return None  # let LLM or fallback handle

    from ..tools.ops_http import focus_store_list
    scope = request.store_id or (request.context or {}).get("store_id")
    stores = focus_store_list(stores, scope)

    any_signal = False
    signals = []
    for s in stores:
        sid = s.get("id")
        if not sid:
            continue
        sig = await compute_pricing_signal(sid)
        signals.append(sig)
        if sig.get("signal") in ("overload", "underload"):
            any_signal = True

    if not any_signal:
        return {
            "status": "ok",
            "summary": "No overload/underload signal — skipped LLM",
            "stores_evaluated": len(signals),
            "suggestions_sent": 0,
            "skipped_llm": True,
            "tools_used": ["compute_pricing_signal"],
            "proposals": [],
            "signals": [{"store_id": s.get("store_id"), "signal": s.get("signal")} for s in signals],
        }
    # Attach signals for the LLM context
    request.context = dict(request.context or {})
    request.context["signals"] = signals
    return None


def _pricing_llm_runner():
    from ..runtime.ops_llm import make_ops_llm_runner
    from ..runtime.wrap import AGENT_ALLOWLISTS

    return make_ops_llm_runner(
        instruction=PRICING_INSTRUCTION,
        tool_names=list(AGENT_ALLOWLISTS["dynamic_pricing"]),
        pre_gate=_pricing_pre_gate,
    )


async def run_dynamic_pricing(store_id: Optional[str] = None):
    """Public entry — runtime with pre-gated LLM tool loop + rule fallback."""
    from ..runtime.wrap import run_ops_agent
    from ..runtime.ops_llm import ops_prefer_llm
    from ..services.demo_backend import demo_focus_store_id, demo_mode

    if not store_id and demo_mode():
        store_id = demo_focus_store_id()

    async def _fallback():
        return await _rule_run_dynamic_pricing(scope_store_id=store_id)

    prefer = ops_prefer_llm()
    return await run_ops_agent(
        "dynamic_pricing",
        "scheduled",
        _fallback,
        store_id=store_id,
        goal="Suggest temporary price adjustments when kitchen is overloaded or underloaded",
        context={"store_id": store_id} if store_id else {},
        llm_runner=_pricing_llm_runner() if prefer else None,
        prefer_llm=prefer,
    )


async def _rule_run_dynamic_pricing(scope_store_id: Optional[str] = None) -> Dict[str, Any]:
    """Suggest price adjustments based on real-time demand vs capacity."""
    from ..tools.ops_http import agent_token
    from ..runtime.models import ActionProposal
    from ..services.demo_backend import demo_focus_store_id, demo_mode

    if not agent_token():
        logger.warning("AGENT_TOKEN not set — dynamic pricing skipped")
        return {"error": "AGENT_TOKEN not configured"}

    now = datetime.now()
    current_hour = now.hour
    suggestions_sent = 0
    stores_evaluated = 0
    proposals: List[Dict[str, Any]] = []
    tools_used: List[str] = ["compute_pricing_signal"]
    reasoning_trace: List[Dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=20.0) as client:
        stores = await _get_stores(client)
        from ..tools.ops_http import focus_store_list
        scope = scope_store_id or (demo_focus_store_id() if demo_mode() else None)
        stores = focus_store_list(stores, scope)

        for store in stores:
            store_id = store["id"]
            store_name = store.get("name", store_id)

            # Evaluate demand state for this store
            active_count = await _count_active_orders(client, store_id)
            recent_count = await _count_recent_orders(client, store_id, minutes=30)
            stores_evaluated += 1

            hours_to_close = STORE_CLOSE_HOUR - current_hour
            signal = "none"
            items: List[Dict] = []
            direction = ""
            percent = 0
            message = ""

            if active_count > OVERLOAD_ACTIVE_ORDERS:
                signal = "overload"
                direction = "increase"
                percent = PRICE_INCREASE_PCT
                items = await _get_top_items(client, store_id, limit=5)
                if items:
                    message = _overload_message(store_name, active_count, items, PRICE_INCREASE_PCT)
                    sent = await _notify_managers(
                        client, store_id, message, priority="HIGH"
                    )
                    suggestions_sent += sent
                    logger.info(
                        "Dynamic Pricing: overload suggestion for store %s (%d active orders)",
                        store_id, active_count,
                    )

            elif (
                recent_count < UNDERLOAD_ORDERS_30MIN
                and hours_to_close >= MIN_HOURS_BEFORE_CLOSE
            ):
                signal = "underload"
                direction = "discount"
                percent = PRICE_DISCOUNT_PCT
                items = await _get_slow_items(client, store_id, limit=5)
                if items:
                    message = _underload_message(
                        store_name, recent_count, items, PRICE_DISCOUNT_PCT, hours_to_close
                    )
                    sent = await _notify_managers(
                        client, store_id, message, priority="MEDIUM"
                    )
                    suggestions_sent += sent
                    logger.info(
                        "Dynamic Pricing: slow-period discount suggestion for store %s (%d orders/30min)",
                        store_id, recent_count,
                    )
            else:
                logger.debug(
                    "Dynamic Pricing: no action for store %s (active=%d, recent=%d)",
                    store_id, active_count, recent_count,
                )

            if signal != "none" and items:
                line_items = [
                    {
                        "itemName": it.get("name") or it.get("itemName") or "Item",
                        "quantity": percent,
                        "unit": "%",
                        "menuItemId": it.get("id"),
                    }
                    for it in items
                ]
                prop = ActionProposal(
                    type="SUGGEST_PRICE_ADJUSTMENT",
                    store_id=store_id,
                    summary=f"{signal.title()} pricing · {store_name}",
                    rationale=message or f"{signal} signal with {len(items)} item(s)",
                    payload={
                        "signal": signal,
                        "direction": direction,
                        "percent": percent,
                        "active_orders": active_count,
                        "recent_orders_30m": recent_count,
                        "message": message,
                        "items": line_items,
                    },
                    evidence=[
                        {
                            "tool": "compute_pricing_signal",
                            "row_id": store_id,
                            "field": "signal",
                            "value": signal,
                        },
                        {
                            "tool": "count_active_orders",
                            "row_id": store_id,
                            "field": "count",
                            "value": active_count,
                        },
                    ],
                    requires_approval=True,
                    agent="dynamic_pricing",
                )
                proposals.append(prop.to_dict())

    if stores_evaluated:
        reasoning_trace.append({
            "index": 0,
            "tool_name": "compute_pricing_signal",
            "args": {"store_id": scope or "fleet"},
            "result_status": "ok",
            "result_summary": f"Evaluated {stores_evaluated} store(s); {len(proposals)} signal(s).",
            "duration_ms": 0.0,
            "at": datetime.now().isoformat(),
        })
    if suggestions_sent:
        tools_used.append("notify_managers")
        reasoning_trace.append({
            "index": 1,
            "tool_name": "notify_managers",
            "args": {},
            "result_status": "ok",
            "result_summary": f"Notified managers for {suggestions_sent} suggestion(s).",
            "duration_ms": 0.0,
            "at": datetime.now().isoformat(),
        })

    logger.info(
        "Dynamic Pricing run complete: %d stores evaluated, %d suggestions sent",
        stores_evaluated, suggestions_sent,
    )
    return {
        "status": "ok",
        "stores_evaluated": stores_evaluated,
        "suggestions_sent": suggestions_sent,
        "evaluated_at": datetime.now().isoformat(),
        "summary": f"Rule fallback: {len(proposals)} pricing proposal(s) across {stores_evaluated} store(s)",
        "proposals": proposals,
        "tools_used": tools_used,
        "reasoning_trace": reasoning_trace,
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


async def _count_active_orders(client, store_id: str) -> int:
    """Count orders that are currently being prepared (not yet delivered/cancelled)."""
    from ..tools.ops_http import get_json, unwrap_list

    from ..tools.ops_tools import ACTIVE_KITCHEN_STATUS_CSV
    active_statuses = ACTIVE_KITCHEN_STATUS_CSV
    status, data = await get_json(
        client,
        "/api/orders",
        params={"storeId": store_id, "status": active_statuses},
    )
    if status != 200:
        return 0
    items = unwrap_list(data)
    total = data.get("totalElements", len(items)) if isinstance(data, dict) else len(items)
    return total


async def _count_recent_orders(
    client, store_id: str, minutes: int
) -> int:
    """Count orders placed in the last N minutes."""
    from ..tools.ops_http import get_json, unwrap_list

    since = (datetime.now() - timedelta(minutes=minutes)).isoformat()
    status, data = await get_json(
        client,
        "/api/orders",
        params={"storeId": store_id, "from": since},
    )
    if status != 200:
        return 0
    items = unwrap_list(data)
    return data.get("totalElements", len(items)) if isinstance(data, dict) else len(items)


async def _get_top_items(
    client, store_id: str, limit: int
) -> List[Dict]:
    """Top selling items by volume today."""
    from ..tools.ops_http import get_json

    status, raw = await get_json(
        client,
        "/api/analytics",
        params={"storeId": store_id, "type": "top-products"},
    )
    if status != 200:
        return []
    items = raw.get("topItems") or raw.get("items") or raw.get("content") or (
        raw if isinstance(raw, list) else []
    )
    return items[:limit]


async def _get_slow_items(
    client, store_id: str, limit: int
) -> List[Dict]:
    """Items with low order volume today — candidates for a discount nudge."""
    from ..tools.ops_http import get_json, unwrap_list

    status, data = await get_json(
        client,
        "/api/menu",
        params={"storeId": store_id, "available": "true"},
    )
    if status != 200:
        return []
    all_items = unwrap_list(data)

    # Get top items to exclude them from slow candidates
    top = await _get_top_items(client, store_id, limit=10)
    top_ids = {item.get("id") for item in top}

    slow = [item for item in all_items if item.get("id") not in top_ids]
    return slow[:limit]


def _overload_message(
    store_name: str, active_count: int, items: List[Dict], increase_pct: int
) -> str:
    item_names = ", ".join(i.get("name", "?") for i in items)
    return (
        f"🔴 Kitchen Overload — {store_name}\n"
        f"{active_count} active orders in queue. Consider a temporary {increase_pct}% price "
        f"increase on high-demand items to slow incoming orders:\n"
        f"• {item_names}\n\n"
        f"Tap 'Apply' to update prices. Prices will revert automatically in 30 minutes."
    )


def _underload_message(
    store_name: str, recent_count: int, items: List[Dict], discount_pct: int, hours_to_close: int
) -> str:
    item_names = ", ".join(i.get("name", "?") for i in items)
    return (
        f"🟡 Slow Period — {store_name}\n"
        f"Only {recent_count} orders in the last 30 min, {hours_to_close}h until close. "
        f"Consider a {discount_pct}% limited-time discount on:\n"
        f"• {item_names}\n\n"
        f"Tap 'Apply' to activate. Discounts expire at closing time automatically."
    )


async def _notify_managers(
    client, store_id: str, message: str, priority: str = "MEDIUM"
) -> int:
    from ..tools.ops_http import get_json, post_json, unwrap_list

    status, managers = await get_json(
        client,
        "/api/users",
        params={"type": "MANAGER", "storeId": store_id},
    )
    if status != 200:
        return 0

    count = 0
    for manager in unwrap_list(managers):
        post_status, _ = await post_json(
            client,
            "/api/notifications",
            {
                "userId": manager["id"],
                "type": "DYNAMIC_PRICING_SUGGESTION",
                "title": "Price Adjustment Suggestion",
                "message": message,
                "priority": priority,
            },
        )
        if post_status in (200, 201):
            count += 1
    return count
