"""
Agent 3: Inventory Reorder
Schedule: Every 6 hours
Input: Current stock levels + demand forecast for next 24h
Logic: If low stock → draft PO (PROPOSE) + notify manager
Output: POST /api/purchase-orders/auto-generate with DRAFT status
        POST /api/notifications to notify manager

LLM path: multi-step tool loop (list_low_stock → forecast → create_draft_po → notify).
Fallback: threshold-based draft PO rule path.
"""
import httpx
import logging
from datetime import datetime
from typing import Dict, List, Any

logger = logging.getLogger(__name__)

INVENTORY_INSTRUCTION = """You are MaSoVa Inventory Reorder Agent (ops).

Goal: Keep stores stocked without over-ordering. You PROPOSE draft purchase orders only.

Workflow:
1. Call list_low_stock (optionally scoped by store).
2. Optionally call get_forecast_snippet for high-risk SKUs — use tool numbers only.
3. Group items by preferred_supplier_id and call create_draft_po with justified quantities
   from reorder_quantity / forecast data (never invent stock counts).
4. Call notify_managers with a clear summary and rationale.

Do not claim orders are finalized. Manager approval is required.
"""


async def _inventory_pre_gate(request):
    """Skip LLM when no low-stock items (cheap signal gate)."""
    forced = (request.context or {}).get("force_low_stock")
    if forced is False:
        return {
            "status": "ok",
            "summary": "No low stock — skipped LLM",
            "pos_drafted": 0,
            "skipped_llm": True,
            "tools_used": [],
            "proposals": [],
        }
    if forced is True:
        return None
    try:
        from ..tools.ops_tools import list_low_stock

        store_id = request.store_id or ""
        res = await list_low_stock(store_id)
        items = res.get("items") or []
        if res.get("ok") and not items:
            return {
                "status": "ok",
                "summary": "No low stock — skipped LLM",
                "pos_drafted": 0,
                "items_checked": 0,
                "skipped_llm": True,
                "tools_used": ["list_low_stock"],
                "proposals": [],
            }
        request.context = dict(request.context or {})
        request.context["low_stock_count"] = len(items)
    except Exception:
        return None
    return None


def _inventory_llm_runner():
    from ..runtime.ops_llm import make_ops_llm_runner
    from ..runtime.wrap import AGENT_ALLOWLISTS

    return make_ops_llm_runner(
        instruction=INVENTORY_INSTRUCTION,
        tool_names=list(AGENT_ALLOWLISTS["inventory_reorder"]),
        pre_gate=_inventory_pre_gate,
    )


async def run_inventory_reorder():
    """Public entry — routes through AgentRuntime with LLM tool loop + rule fallback."""
    from ..runtime.wrap import run_ops_agent
    from ..runtime.ops_llm import ops_prefer_llm

    return await run_ops_agent(
        "inventory_reorder",
        "scheduled",
        _rule_run_inventory_reorder,
        goal="Identify low stock and draft purchase orders for manager approval",
        llm_runner=_inventory_llm_runner() if ops_prefer_llm() else None,
        prefer_llm=ops_prefer_llm(),
    )


async def _rule_run_inventory_reorder() -> Dict[str, Any]:
    """Rule fallback. Returns summary of POs drafted."""
    from ..tools.ops_http import get_json, post_json, unwrap_list, agent_token
    from ..runtime.models import ActionProposal
    from ..utils.config import get_config

    config = get_config()
    token = config.agent_token or agent_token()
    if not token:
        logger.warning("AGENT_TOKEN not set — inventory reorder skipped")
        return {"error": "AGENT_TOKEN not configured"}

    pos_drafted = 0
    items_checked = 0
    proposals: List[Dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        stores = await _get_stores(client)

        for store in stores:
            store_id = store["id"]

            st, inv_items = await get_json(
                client,
                "/api/inventory",
                params={"storeId": store_id, "lowStock": "true"},
            )
            if st != 200 or not inv_items:
                continue

            inv_list = unwrap_list(inv_items)
            items_checked += len(inv_list)

            # Group by preferred supplier
            supplier_items: Dict[str, List[Dict]] = {}
            for item in inv_list:
                supplier_id = item.get("preferredSupplierId") or item.get("supplierId")
                if not supplier_id:
                    continue
                supplier_items.setdefault(supplier_id, []).append(item)

            # Draft a PO per supplier
            for supplier_id, items in supplier_items.items():
                po_items = [
                    {
                        "inventoryItemId": item["id"],
                        "itemName": item.get("itemName") or item.get("name", "Unknown"),
                        "quantity": item.get("reorderQuantity", 10),
                        "unitCost": item.get("unitCost", 0),
                    }
                    for item in items
                ]
                po_payload = {
                    "storeId": store_id,
                    "supplierId": supplier_id,
                    "status": "DRAFT",
                    "autoGenerated": True,
                    "generatedAt": datetime.now().isoformat(),
                    "items": po_items,
                    "notes": f"Auto-generated by Inventory Reorder Agent at {datetime.now().isoformat()}",
                }

                pst, pres = await post_json(
                    client,
                    "/api/purchase-orders/auto-generate",
                    po_payload,
                )

                if pst in (200, 201):
                    pos_drafted += 1
                    po_id = pres.get("id") if isinstance(pres, dict) else ""
                    item_names = ", ".join(i.get("itemName") or i.get("name", "?") for i in items[:3])
                    more = f" and {len(items) - 3} more" if len(items) > 3 else ""
                    await _notify_manager(
                        client, store_id,
                        f"Inventory Alert: {item_names}{more} need reordering. Draft PO created — please review.",
                    )
                    prop = ActionProposal(
                        type="DRAFT_PURCHASE_ORDER",
                        store_id=store_id,
                        summary=f"Draft purchase order ({len(items)} items from {supplier_id})",
                        rationale=f"Low stock detected for {item_names}{more}",
                        payload={
                            "supplier_id": supplier_id,
                            "items": po_items,
                            "po_id": po_id,
                        },
                        requires_approval=True,
                        agent="inventory_reorder",
                    )
                    proposals.append(prop.to_dict())

    logger.info("Inventory reorder complete: %d POs drafted, %d items checked", pos_drafted, items_checked)
    return {
        "pos_drafted": pos_drafted,
        "items_checked": items_checked,
        "summary": f"Rule fallback: {pos_drafted} draft PO(s), {items_checked} items checked",
        "status": "ok",
        "proposals": proposals,
    }


async def _get_stores(client: httpx.AsyncClient) -> List[Dict]:
    from ..tools.ops_http import get_json, unwrap_list
    st, data = await get_json(client, "/api/stores")
    if st != 200 or not data:
        return []
    return unwrap_list(data)


async def _notify_manager(client: httpx.AsyncClient, store_id: str, message: str):
    """Send notification to all managers for a store."""
    from ..tools.ops_http import get_json, post_json, unwrap_list
    st, managers_data = await get_json(
        client,
        "/api/users",
        params={"type": "MANAGER", "storeId": store_id},
    )
    if st != 200 or not managers_data:
        return

    managers = unwrap_list(managers_data)
    for manager in managers:
        await post_json(
            client,
            "/api/notifications",
            {
                "userId": manager.get("id"),
                "type": "INVENTORY_ALERT",
                "title": "Inventory Reorder Required",
                "message": message,
                "priority": "HIGH",
            },
        )

