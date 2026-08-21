"""
Agent 2: Demand Forecasting
Schedule: Nightly at 2am IST
Input: 90-day order history per menu item per hour per day-of-week
Method: Weighted moving average (recent days weighted higher) + day-of-week seasonality
Output: Writes to /api/analytics/forecast endpoint as daily_forecasts records
"""
import httpx
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Any

logger = logging.getLogger(__name__)


def _get_config():
    """Lazy import config to avoid circular imports."""
    from ..utils.config import get_config
    return get_config()




DEMAND_INSTRUCTION = """You are MaSoVa Demand Forecast Agent (ops).

Source of truth for ALL numeric forecasts is the COMPUTE tool compute_wma_forecast
using series from read_order_metrics / order history tools. You may only summarize
anomalies and call write_forecast / notify_managers with those tool numbers.

Never invent stock, order counts, or forecast values. If tools return empty series,
report no forecast — do not guess.
"""


def _demand_llm_runner():
    from ..runtime.ops_llm import make_ops_llm_runner
    from ..runtime.wrap import AGENT_ALLOWLISTS

    return make_ops_llm_runner(
        instruction=DEMAND_INSTRUCTION,
        tool_names=list(AGENT_ALLOWLISTS["demand_forecast"]),
    )


async def run_demand_forecast():
    """Public entry — runtime with optional LLM summarize loop + rule fallback."""
    from ..runtime.wrap import run_ops_agent
    from ..runtime.ops_llm import ops_prefer_llm

    prefer = ops_prefer_llm()
    return await run_ops_agent(
        "demand_forecast",
        "scheduled",
        _rule_run_demand_forecast,
        goal="Compute WMA demand forecasts and write daily_forecast records",
        llm_runner=_demand_llm_runner() if prefer else None,
        prefer_llm=prefer,
    )

async def _rule_run_demand_forecast() -> Dict[str, Any]:
    """Main entry point — called by APScheduler nightly at 2am."""
    config = _get_config()
    backend_url = config.backend_url
    agent_token = config.agent_token

    if not agent_token:
        logger.warning("AGENT_TOKEN not set — demand forecast skipped")
        return {"error": "AGENT_TOKEN not configured"}

    headers = {"Authorization": f"Bearer {agent_token}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        stores_res = await client.get(f"{backend_url}/api/stores", headers=headers)
        if stores_res.status_code != 200:
            logger.error("Failed to fetch stores: %s", stores_res.text)
            return {"error": "Could not fetch stores"}

        stores = stores_res.json()
        store_ids = [s["id"] for s in ((stores if isinstance(stores, list) else stores.get('content') or []))]

        total_forecasts = 0
        for store_id in store_ids:
            count = await _forecast_for_store(client, backend_url, headers, store_id)
            total_forecasts += count

    logger.info("Demand forecast complete: %d forecasts for %d stores", total_forecasts, len(store_ids))
    return {"forecasts": total_forecasts, "stores": len(store_ids), "generated_at": datetime.now().isoformat()}


async def _forecast_for_store(
    client: httpx.AsyncClient,
    backend_url: str,
    headers: dict,
    store_id: str,
) -> int:
    """Generate demand forecasts for a single store. Returns count of forecasts written."""
    since = (datetime.now() - timedelta(days=90)).isoformat()
    orders_res = await client.get(
        f"{backend_url}/api/orders",
        params={"storeId": store_id, "from": since, "status": "DELIVERED,COMPLETED,SERVED"},
        headers=headers,
    )

    if orders_res.status_code != 200:
        logger.warning("Failed to fetch orders for store %s", store_id)
        return 0

    orders = orders_res.json()
    orders_list = (orders if isinstance(orders, list) else orders.get('content') or [])
    if not orders_list:
        return 0

    # Aggregate: { menuItemId: { day_of_week: { hour: [quantities] } } }
    history: Dict[str, Dict[int, Dict[int, List[float]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )

    for order in orders_list:
        created_at_str = order.get("createdAt", "")
        if not created_at_str:
            continue
        created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
        day_of_week = created_at.weekday()
        hour = created_at.hour

        for item in order.get("items", []):
            menu_item_id = item.get("menuItemId")
            qty = item.get("quantity", 0)
            if menu_item_id and qty > 0:
                history[menu_item_id][day_of_week][hour].append(qty)

    # Generate tomorrow's forecast
    tomorrow = datetime.now() + timedelta(days=1)
    tomorrow_dow = tomorrow.weekday()
    forecast_date = tomorrow.strftime("%Y-%m-%d")

    forecasts_written = 0

    for menu_item_id, day_hour_data in history.items():
        hour_data = day_hour_data.get(tomorrow_dow, {})

        for hour in range(24):
            quantities = hour_data.get(hour, [])
            if not quantities:
                continue

            # Weighted moving average — recent observations weighted higher
            n = len(quantities)
            weights = [1 + (i / n) for i in range(n)]
            weighted_sum = sum(q * w for q, w in zip(quantities, weights))
            weight_total = sum(weights)
            predicted_qty = round(weighted_sum / weight_total, 2)

            forecast_payload = {
                "storeId": store_id,
                "date": forecast_date,
                "menuItemId": menu_item_id,
                "hourSlot": hour,
                "predictedQuantity": predicted_qty,
                "dayOfWeek": tomorrow_dow,
                "generatedAt": datetime.now().isoformat(),
                "agentVersion": "2.0",
            }

            res = await client.post(
                f"{backend_url}/api/analytics/forecast",
                json=forecast_payload,
                headers=headers,
            )

            if res.status_code in (200, 201):
                forecasts_written += 1
            else:
                logger.warning(
                    "Failed to write forecast for item %s hour %d: %s",
                    menu_item_id, hour, res.text[:100],
                )

    return forecasts_written
