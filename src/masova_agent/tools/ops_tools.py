"""
Ops agent tools: READ / COMPUTE / PROPOSE only (never EXECUTE).

All tools are async and return dict (ADK-compatible). PROPOSE tools return
ActionProposal-compatible dicts with requires_approval=true.
Numbers (stock, forecasts, order counts, prices) come only from tools — not LLM invention.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx

from .ops_http import agent_token, get_json, post_json, unwrap_list

logger = logging.getLogger(__name__)

# Pricing bounds (must match dynamic_pricing_agent constants)
PRICE_INCREASE_PCT_MAX = 12
PRICE_DISCOUNT_PCT_MAX = 15
OVERLOAD_ACTIVE_ORDERS = 15
UNDERLOAD_ORDERS_30MIN = 3


def _proposal(
    type_: str,
    store_id: str,
    summary: str,
    rationale: str,
    payload: Optional[dict] = None,
    idempotency_key: str = "",
    agent: str = "",
) -> dict[str, Any]:
    """Canonical ActionProposal-shaped dict (see runtime.models.ActionProposal)."""
    from ..runtime.models import ActionProposal

    p = ActionProposal(
        type=type_,
        store_id=store_id or "",
        summary=summary,
        rationale=rationale,
        payload=payload or {},
        requires_approval=True,
        agent=agent,
        idempotency_key=idempotency_key or "",
    )
    if idempotency_key:
        p.payload = dict(p.payload)
        p.payload["idempotency_key"] = idempotency_key
    return p.to_dict()


def _require_token() -> Optional[dict]:
    if not agent_token():
        return {"ok": False, "error": "AGENT_TOKEN not configured"}
    return None


# ---------------------------------------------------------------------------
# READ
# ---------------------------------------------------------------------------

async def list_stores() -> dict[str, Any]:
    """List stores available to the agent."""
    err = _require_token()
    if err:
        return err
    async with httpx.AsyncClient(timeout=20.0) as client:
        status, body = await get_json(client, "/api/stores")
        if status != 200:
            return {"ok": False, "error": f"stores_http_{status}", "stores": []}
        stores = unwrap_list(body)
        return {
            "ok": True,
            "stores": [
                {"id": s.get("id"), "name": s.get("name", s.get("id"))}
                for s in stores
                if s.get("id")
            ],
        }


async def list_low_stock(store_id: str = "") -> dict[str, Any]:
    """Low-stock inventory items for a store (or all stores if store_id empty)."""
    err = _require_token()
    if err:
        return err
    async with httpx.AsyncClient(timeout=20.0) as client:
        if store_id:
            store_ids = [store_id]
        else:
            st, body = await get_json(client, "/api/stores")
            if st != 200:
                return {"ok": False, "error": f"stores_http_{st}", "items": []}
            store_ids = [s["id"] for s in unwrap_list(body) if s.get("id")]

        items: list[dict] = []
        for sid in store_ids:
            st, body = await get_json(
                client, "/api/inventory", params={"storeId": sid, "lowStock": "true"}
            )
            if st != 200:
                continue
            for item in unwrap_list(body):
                items.append({
                    "id": item.get("id"),
                    "store_id": sid,
                    "item_name": item.get("itemName") or item.get("name", "Unknown"),
                    "current_stock": item.get("currentStock") or item.get("quantity"),
                    "minimum_stock": item.get("minimumStock") or item.get("minStock"),
                    "reorder_quantity": item.get("reorderQuantity", 10),
                    "unit_cost": item.get("unitCost", 0),
                    "preferred_supplier_id": item.get("preferredSupplierId"),
                })
        return {"ok": True, "items": items, "count": len(items)}


async def get_forecast_snippet(
    store_id: str,
    item_id: str = "",
    hours: int = 24,
) -> dict[str, Any]:
    """Demand forecast snippet for inventory planning (READ)."""
    err = _require_token()
    if err:
        return err
    async with httpx.AsyncClient(timeout=20.0) as client:
        params: dict[str, Any] = {"storeId": store_id, "hours": hours}
        if item_id:
            params["itemId"] = item_id
        st, body = await get_json(client, "/api/analytics/forecast", params=params)
        if st != 200:
            return {"ok": False, "error": f"forecast_http_{st}", "forecasts": []}
        forecasts = body if isinstance(body, list) else (
            body.get("forecasts") or body.get("content") or []
        )
        # Compact for LLM context
        snippet = []
        for f in (forecasts or [])[:50]:
            if not isinstance(f, dict):
                continue
            snippet.append({
                "item_id": f.get("itemId") or f.get("menuItemId"),
                "predicted_qty": f.get("predictedQty") or f.get("quantity") or f.get("demand"),
                "hour": f.get("hour"),
                "day": f.get("day") or f.get("date"),
            })
        return {"ok": True, "store_id": store_id, "forecasts": snippet}


async def count_active_orders(store_id: str) -> dict[str, Any]:
    """Count orders currently in kitchen pipeline."""
    err = _require_token()
    if err:
        return err
    active_statuses = "RECEIVED,PREPARING,OVEN,BAKED,READY"
    async with httpx.AsyncClient(timeout=20.0) as client:
        st, body = await get_json(
            client,
            "/api/orders",
            params={"storeId": store_id, "status": active_statuses},
        )
        if st != 200:
            return {"ok": False, "error": f"orders_http_{st}", "count": 0}
        items = unwrap_list(body) if not isinstance(body, dict) else (
            body.get("content") or (body if isinstance(body, list) else [])
        )
        if isinstance(body, dict) and "totalElements" in body:
            total = body["totalElements"]
        else:
            total = len(items) if isinstance(items, list) else 0
        return {"ok": True, "store_id": store_id, "count": int(total)}


async def count_recent_orders(store_id: str, minutes: int = 30) -> dict[str, Any]:
    """Count orders placed in the last N minutes."""
    err = _require_token()
    if err:
        return err
    since = (datetime.now() - timedelta(minutes=minutes)).isoformat()
    async with httpx.AsyncClient(timeout=20.0) as client:
        st, body = await get_json(
            client,
            "/api/orders",
            params={"storeId": store_id, "from": since},
        )
        if st != 200:
            return {"ok": False, "error": f"orders_http_{st}", "count": 0}
        if isinstance(body, dict) and "totalElements" in body:
            total = body["totalElements"]
        else:
            total = len(unwrap_list(body))
        return {"ok": True, "store_id": store_id, "minutes": minutes, "count": int(total)}


async def get_top_items(store_id: str, limit: int = 5) -> dict[str, Any]:
    """Top selling items by volume (analytics)."""
    err = _require_token()
    if err:
        return err
    async with httpx.AsyncClient(timeout=20.0) as client:
        st, body = await get_json(
            client, "/api/analytics/products", params={"storeId": store_id}
        )
        if st != 200:
            return {"ok": False, "error": f"analytics_http_{st}", "items": []}
        raw = body or {}
        items = raw.get("topItems") or raw.get("items") or (
            raw if isinstance(raw, list) else []
        )
        out = []
        for i in (items or [])[: max(1, min(limit, 20))]:
            if isinstance(i, dict):
                out.append({
                    "id": i.get("id"),
                    "name": i.get("name", "?"),
                    "price": i.get("price"),
                    "volume": i.get("volume") or i.get("orderCount"),
                })
        return {"ok": True, "store_id": store_id, "items": out}


async def get_slow_items(store_id: str, limit: int = 5) -> dict[str, Any]:
    """Available menu items not in today's top sellers — discount candidates."""
    err = _require_token()
    if err:
        return err
    async with httpx.AsyncClient(timeout=20.0) as client:
        st, body = await get_json(
            client, "/api/menu", params={"storeId": store_id, "available": "true"}
        )
        if st != 200:
            return {"ok": False, "error": f"menu_http_{st}", "items": []}
        all_items = unwrap_list(body)
        top = await get_top_items(store_id, limit=10)
        top_ids = {i.get("id") for i in top.get("items") or []}
        slow = [i for i in all_items if i.get("id") not in top_ids]
        out = []
        for i in slow[: max(1, min(limit, 20))]:
            out.append({
                "id": i.get("id"),
                "name": i.get("name", "?"),
                "price": i.get("price"),
            })
        return {"ok": True, "store_id": store_id, "items": out}


async def get_order_context(order_id: str) -> dict[str, Any]:
    """Order details for review response drafting."""
    err = _require_token()
    if err:
        return err
    if not order_id:
        return {"ok": False, "error": "order_id required"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        st, body = await get_json(client, f"/api/orders/{order_id}")
        if st != 200:
            return {"ok": False, "error": f"order_http_{st}"}
        order = body if isinstance(body, dict) else {}
        items = order.get("items") or []
        return {
            "ok": True,
            "order_id": order_id,
            "store_id": order.get("storeId"),
            "items": [
                {"name": i.get("name", "?"), "qty": i.get("quantity", 1)}
                for i in items if isinstance(i, dict)
            ],
            "status": order.get("status"),
        }


async def read_churn_segment(store_id: str) -> dict[str, Any]:
    """Customers likely to churn (high-value, inactive)."""
    err = _require_token()
    if err:
        return err
    churn_window = 14
    qualifying_count = 3
    qualifying_period = 60
    now = datetime.now()
    period_start = (now - timedelta(days=qualifying_period)).isoformat()
    churn_cutoff = (now - timedelta(days=churn_window)).isoformat()

    async with httpx.AsyncClient(timeout=30.0) as client:
        st, body = await get_json(
            client,
            "/api/customers",
            params={"storeId": store_id, "minOrders": qualifying_count},
        )
        if st != 200:
            return {"ok": False, "error": f"customers_http_{st}", "customers": []}
        candidates = unwrap_list(body)
        churned: list[dict] = []
        for c in candidates:
            cid = c.get("id")
            if not cid:
                continue
            ost, obody = await get_json(
                client,
                "/api/orders",
                params={
                    "customerId": cid,
                    "from": period_start,
                    "status": "DELIVERED,COMPLETED,SERVED",
                },
            )
            if ost != 200:
                continue
            orders = unwrap_list(obody)
            if isinstance(obody, dict) and "content" in obody:
                orders = unwrap_list(obody)
            if len(orders) < qualifying_count:
                continue
            last_dates = []
            for o in orders:
                d = o.get("createdAt") or o.get("orderDate")
                if d:
                    last_dates.append(str(d))
            if not last_dates:
                continue
            last = max(last_dates)
            if last < churn_cutoff:
                churned.append({
                    "id": cid,
                    "name": c.get("name") or c.get("firstName", "customer"),
                    "last_order_at": last,
                    "order_count_60d": len(orders),
                })
        return {
            "ok": True,
            "store_id": store_id,
            "customers": churned[:100],
            "count": len(churned),
            "rules": {
                "churn_window_days": churn_window,
                "min_orders": qualifying_count,
                "period_days": qualifying_period,
            },
        }


async def read_staff_slots(store_id: str) -> dict[str, Any]:
    """Staff pool for shift drafting."""
    err = _require_token()
    if err:
        return err
    roles = {"KITCHEN_STAFF", "CASHIER", "DRIVER"}
    async with httpx.AsyncClient(timeout=20.0) as client:
        st, body = await get_json(
            client, "/api/users", params={"storeId": store_id}
        )
        if st != 200:
            return {"ok": False, "error": f"users_http_{st}", "staff": []}
        staff = []
        for u in unwrap_list(body):
            role = (u.get("role") or u.get("type") or "").upper()
            if role in roles or u.get("type") in roles:
                staff.append({
                    "id": u.get("id"),
                    "name": u.get("name") or u.get("fullName", "?"),
                    "role": role or u.get("type"),
                })
        return {"ok": True, "store_id": store_id, "staff": staff}


async def read_kitchen_metrics(store_id: str) -> dict[str, Any]:
    """Today's kitchen performance metrics."""
    err = _require_token()
    if err:
        return err
    async with httpx.AsyncClient(timeout=20.0) as client:
        st, body = await get_json(
            client,
            "/api/analytics/orders",
            params={"storeId": store_id, "period": "today"},
        )
        if st != 200:
            return {"ok": False, "error": f"metrics_http_{st}"}
        m = body if isinstance(body, dict) else {}
        return {
            "ok": True,
            "store_id": store_id,
            "avg_prep_minutes": m.get("avgPrepTimeMinutes") or m.get("avgPrepMinutes"),
            "ticket_count": m.get("ticketCount") or m.get("orderCount") or 0,
            "slow_tickets": m.get("slowTickets") or 0,
            "raw_keys": list(m.keys())[:20],
        }


async def read_order_metrics(store_id: str = "") -> dict[str, Any]:
    """Generic order metrics pack for demand / pricing context."""
    err = _require_token()
    if err:
        return err
    if not store_id:
        stores = await list_stores()
        return {"ok": True, "stores": stores.get("stores", [])}
    active = await count_active_orders(store_id)
    recent = await count_recent_orders(store_id, 30)
    return {
        "ok": True,
        "store_id": store_id,
        "active_orders": active.get("count", 0),
        "recent_30min": recent.get("count", 0),
        "overload_threshold": OVERLOAD_ACTIVE_ORDERS,
        "underload_threshold": UNDERLOAD_ORDERS_30MIN,
    }


# ---------------------------------------------------------------------------
# COMPUTE
# ---------------------------------------------------------------------------

async def compute_pricing_signal(
    store_id: str,
    active_count: int = -1,
    recent_count: int = -1,
    current_hour: int = -1,
) -> dict[str, Any]:
    """
    Deterministic overload/underload signal. LLM must not invent thresholds.
    Returns signal: overload | underload | none.
    """
    if active_count < 0 or recent_count < 0:
        active = await count_active_orders(store_id)
        recent = await count_recent_orders(store_id, 30)
        active_count = int(active.get("count") or 0)
        recent_count = int(recent.get("count") or 0)
    hour = current_hour if current_hour >= 0 else datetime.now().hour
    store_close = 22
    hours_to_close = store_close - hour
    if active_count > OVERLOAD_ACTIVE_ORDERS:
        return {
            "ok": True,
            "signal": "overload",
            "store_id": store_id,
            "active_count": active_count,
            "recent_count": recent_count,
            "suggested_pct": PRICE_INCREASE_PCT_MAX,
            "direction": "increase",
            "hours_to_close": hours_to_close,
        }
    if recent_count < UNDERLOAD_ORDERS_30MIN and hours_to_close >= 2:
        return {
            "ok": True,
            "signal": "underload",
            "store_id": store_id,
            "active_count": active_count,
            "recent_count": recent_count,
            "suggested_pct": PRICE_DISCOUNT_PCT_MAX,
            "direction": "discount",
            "hours_to_close": hours_to_close,
        }
    return {
        "ok": True,
        "signal": "none",
        "store_id": store_id,
        "active_count": active_count,
        "recent_count": recent_count,
        "hours_to_close": hours_to_close,
    }


async def compute_wma_forecast(
    series: Optional[list] = None,
    weights: Optional[list] = None,
) -> dict[str, Any]:
    """
    Weighted moving average over a numeric series (most recent last).
    Pure COMPUTE — no side effects.
    """
    series = series or []
    if not series:
        return {"ok": False, "error": "empty_series", "forecast": 0.0}
    nums = [float(x) for x in series]
    if weights is None:
        # Default: linear weights favoring recent points
        weights = list(range(1, len(nums) + 1))
    if len(weights) != len(nums):
        weights = list(range(1, len(nums) + 1))
    w = [float(x) for x in weights]
    total_w = sum(w) or 1.0
    forecast = sum(n * wi for n, wi in zip(nums, w)) / total_w
    return {
        "ok": True,
        "forecast": round(forecast, 4),
        "n": len(nums),
        "method": "weighted_moving_average",
    }


# ---------------------------------------------------------------------------
# PROPOSE (draft + notify only — never final execute)
# ---------------------------------------------------------------------------

async def create_draft_po(
    store_id: str,
    supplier_id: str,
    items: Optional[list] = None,
    rationale: str = "",
    notes: str = "",
) -> dict[str, Any]:
    """Draft a purchase order (DRAFT status). Manager must approve."""
    err = _require_token()
    if err:
        return err
    items = items or []
    if not store_id or not supplier_id or not items:
        return {"ok": False, "error": "store_id, supplier_id, and items required"}

    from ..runtime.idempotency import check_or_claim, make_key

    idem_key = make_key(
        "inventory_reorder", store_id, "draft_po", window="hour", extra=supplier_id
    )
    is_new, prior = check_or_claim(idem_key, {"supplier_id": supplier_id})
    if not is_new:
        return {
            "ok": True,
            "duplicate": True,
            "idempotency_key": idem_key,
            "skipped": True,
            "summary": "Duplicate draft PO skipped (same store/supplier/hour)",
            "prior": prior,
            "proposal": None,
        }

    po_items = []
    for it in items:
        if not isinstance(it, dict):
            continue
        po_items.append({
            "inventoryItemId": it.get("inventory_item_id") or it.get("id") or it.get("inventoryItemId"),
            "itemName": it.get("item_name") or it.get("itemName") or it.get("name", "Unknown"),
            "quantity": it.get("quantity") or it.get("reorder_quantity") or 10,
            "unitCost": it.get("unit_cost") or it.get("unitCost") or 0,
        })
    if not po_items:
        return {"ok": False, "error": "no valid items"}

    payload = {
        "storeId": store_id,
        "supplierId": supplier_id,
        "status": "DRAFT",
        "autoGenerated": True,
        "generatedAt": datetime.now().isoformat(),
        "items": po_items,
        "notes": notes or f"Auto-draft by inventory agent: {rationale}"[:500],
        "idempotencyKey": idem_key,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        st, body = await post_json(client, "/api/purchase-orders/auto-generate", payload)
        ok = st in (200, 201)
        proposal = _proposal(
            "DRAFT_PURCHASE_ORDER",
            store_id,
            summary=f"Draft PO for {len(po_items)} item(s) via supplier {supplier_id}",
            rationale=rationale or "Low stock relative to forecast / reorder threshold",
            payload={"supplier_id": supplier_id, "items": po_items, "http_status": st},
            idempotency_key=idem_key,
        )
        return {
            "ok": ok,
            "http_status": st,
            "idempotency_key": idem_key,
            "proposal": proposal,
            "response": body if ok else None,
            "error": None if ok else f"po_http_{st}",
        }


async def notify_managers(
    store_id: str,
    message: str,
    title: str = "Agent Alert",
    notification_type: str = "AGENT_ALERT",
    priority: str = "MEDIUM",
    rationale: str = "",
    proposal_id: str = "",
    proposal_summary: str = "",
) -> dict[str, Any]:
    """Notify store managers (PROPOSE side-effect: notification only)."""
    err = _require_token()
    if err:
        return err
    if not store_id or not message:
        return {"ok": False, "error": "store_id and message required"}
    full_message = message
    if proposal_id and proposal_id not in full_message:
        full_message = f"{full_message}\n\nproposal_id={proposal_id}"
    if proposal_summary and proposal_summary not in full_message:
        full_message = f"{full_message}\nSummary: {proposal_summary}"
    if rationale and rationale not in message:
        full_message = f"{full_message}\n\nRationale: {rationale}"

    async with httpx.AsyncClient(timeout=20.0) as client:
        st, body = await get_json(
            client, "/api/users", params={"type": "MANAGER", "storeId": store_id}
        )
        if st != 200:
            return {"ok": False, "error": f"managers_http_{st}", "sent": 0}
        managers = unwrap_list(body)
        sent = 0
        for manager in managers:
            mid = manager.get("id")
            if not mid:
                continue
            notif_body: dict[str, Any] = {
                "userId": mid,
                "type": notification_type,
                "title": title,
                "message": full_message,
                "priority": priority,
            }
            if proposal_id:
                notif_body["data"] = {
                    "proposal_id": proposal_id,
                    "summary": proposal_summary or title,
                    "rationale": rationale,
                    "requires_approval": True,
                }
            pst, _ = await post_json(
                client,
                "/api/notifications",
                notif_body,
            )
            if pst in (200, 201):
                sent += 1
        proposal = _proposal(
            "NOTIFY_MANAGERS",
            store_id,
            summary=title,
            rationale=rationale or message[:300],
            payload={"sent": sent, "notification_type": notification_type},
        )
        return {"ok": True, "sent": sent, "proposal": proposal}


async def propose_price_suggestion(
    store_id: str,
    direction: str,
    percent: float,
    item_ids: Optional[list] = None,
    item_names: Optional[list] = None,
    rationale: str = "",
    active_count: int = 0,
    recent_count: int = 0,
) -> dict[str, Any]:
    """
    Propose a temporary price adjustment via manager notification only.
    NEVER patches menu prices.
    """
    err = _require_token()
    if err:
        return err
    direction = (direction or "").lower()
    if direction not in ("increase", "discount", "decrease"):
        return {"ok": False, "error": "direction must be increase or discount"}

    if direction == "increase":
        pct = min(abs(float(percent)), PRICE_INCREASE_PCT_MAX)
        direction = "increase"
    else:
        pct = min(abs(float(percent)), PRICE_DISCOUNT_PCT_MAX)
        direction = "discount"

    from ..runtime.idempotency import check_or_claim, make_key

    idem_key = make_key(
        "dynamic_pricing", store_id, f"price_{direction}", window="hour"
    )
    is_new, prior = check_or_claim(idem_key, {"direction": direction, "percent": pct})
    if not is_new:
        return {
            "ok": True,
            "duplicate": True,
            "skipped": True,
            "idempotency_key": idem_key,
            "prior": prior,
            "proposal": None,
            "patches_menu": False,
        }

    names = item_names or []
    ids = item_ids or []
    names_str = ", ".join(str(n) for n in names[:8]) or ", ".join(str(i) for i in ids[:8]) or "selected items"
    if direction == "increase":
        message = (
            f"Kitchen overload signal — suggest temporary {pct:.0f}% price increase on: {names_str}. "
            f"Active orders: {active_count}. Manager approval required; agent does not change prices."
        )
        priority = "HIGH"
        title = "Price Increase Suggestion"
    else:
        message = (
            f"Slow period signal — suggest temporary {pct:.0f}% discount on: {names_str}. "
            f"Recent 30m orders: {recent_count}. Manager approval required; agent does not change prices."
        )
        priority = "MEDIUM"
        title = "Price Discount Suggestion"

    proposal = _proposal(
        "SUGGEST_PRICE_ADJUSTMENT",
        store_id,
        summary=f"{direction} {pct:.0f}% on {names_str[:80]}",
        rationale=rationale or message,
        idempotency_key=idem_key,
        agent="dynamic_pricing",
        payload={
            "direction": direction,
            "percent": pct,
            "item_ids": ids,
            "item_names": names,
            "active_count": active_count,
            "recent_count": recent_count,
            "max_increase_pct": PRICE_INCREASE_PCT_MAX,
            "max_discount_pct": PRICE_DISCOUNT_PCT_MAX,
            "patches_menu": False,
        },
    )
    notify = await notify_managers(
        store_id=store_id,
        message=message,
        title=title,
        notification_type="DYNAMIC_PRICING_SUGGESTION",
        priority=priority,
        rationale=rationale or f"{direction} {pct}% on tool-selected items",
        proposal_id=proposal.get("proposal_id", ""),
        proposal_summary=proposal.get("summary", ""),
    )
    proposal["payload"] = dict(proposal.get("payload") or {})
    proposal["payload"]["notify_sent"] = notify.get("sent", 0)
    return {
        "ok": bool(notify.get("ok")),
        "proposal": proposal,
        "sent": notify.get("sent", 0),
        "patches_menu": False,
        "idempotency_key": idem_key,
    }


async def create_draft_campaign(
    store_id: str,
    customer_ids: Optional[list] = None,
    message: str = "",
    discount_percent: float = 15,
    rationale: str = "",
    name: str = "",
) -> dict[str, Any]:
    """Draft a win-back campaign (DRAFT status)."""
    err = _require_token()
    if err:
        return err
    customer_ids = customer_ids or []
    if not store_id or not customer_ids:
        return {"ok": False, "error": "store_id and customer_ids required"}
    from ..runtime.idempotency import check_or_claim, make_key

    idem_key = make_key("churn_prevention", store_id, "draft_campaign", window="date")
    is_new, prior = check_or_claim(idem_key, {"customer_count": len(customer_ids)})
    if not is_new:
        return {
            "ok": True,
            "duplicate": True,
            "skipped": True,
            "idempotency_key": idem_key,
            "prior": prior,
            "proposal": None,
        }
    payload = {
        "storeId": store_id,
        "name": name or f"Win-Back Campaign — {datetime.now().strftime('%Y-%m-%d')}",
        "type": "WIN_BACK",
        "status": "DRAFT",
        "autoGenerated": True,
        "targetSegment": "CHURNED_HIGH_VALUE",
        "customerIds": customer_ids,
        "discountPercent": discount_percent,
        "message": message or f"We miss you! Enjoy {discount_percent}% off your next order.",
        "expiresInDays": 7,
        "generatedBy": "churn_prevention_agent",
        "generatedAt": datetime.now().isoformat(),
        "rationale": rationale,
        "idempotencyKey": idem_key,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        st, body = await post_json(client, "/api/campaigns", payload)
        ok = st in (200, 201)
        proposal = _proposal(
            "DRAFT_CHURN_CAMPAIGN",
            store_id,
            summary=f"Draft win-back for {len(customer_ids)} customers",
            rationale=rationale or "Churn segment: high-value inactive customers",
            payload={"customer_count": len(customer_ids), "discount_percent": discount_percent},
            idempotency_key=idem_key,
        )
        return {
            "ok": ok,
            "http_status": st,
            "idempotency_key": idem_key,
            "proposal": proposal,
            "error": None if ok else f"campaign_http_{st}",
        }


async def create_draft_shifts(
    store_id: str,
    shifts: Optional[list] = None,
    rationale: str = "",
) -> dict[str, Any]:
    """Bulk draft shifts for manager review."""
    err = _require_token()
    if err:
        return err
    shifts = shifts or []
    if not store_id or not shifts:
        return {"ok": False, "error": "store_id and shifts required"}
    from ..runtime.idempotency import check_or_claim, make_key

    idem_key = make_key("shift_optimisation", store_id, "draft_shifts", window="date")
    is_new, prior = check_or_claim(idem_key, {"shift_count": len(shifts)})
    if not is_new:
        return {
            "ok": True,
            "duplicate": True,
            "skipped": True,
            "idempotency_key": idem_key,
            "prior": prior,
            "proposal": None,
        }
    # Force DRAFT status
    for s in shifts:
        if isinstance(s, dict):
            s["status"] = "DRAFT"
            s["storeId"] = s.get("storeId") or store_id
    async with httpx.AsyncClient(timeout=30.0) as client:
        st, body = await post_json(
            client,
            "/api/shifts/bulk",
            {"storeId": store_id, "shifts": shifts, "status": "DRAFT", "idempotencyKey": idem_key},
        )
        ok = st in (200, 201)
        proposal = _proposal(
            "DRAFT_SHIFT_ROSTER",
            store_id,
            summary=f"Draft {len(shifts)} shift slot(s)",
            rationale=rationale or "Built from forecast demand + staff pool",
            payload={"shift_count": len(shifts)},
            idempotency_key=idem_key,
        )
        return {
            "ok": ok,
            "http_status": st,
            "idempotency_key": idem_key,
            "proposal": proposal,
        }


async def submit_review_draft_notification(
    store_id: str,
    draft_text: str,
    review_id: str = "",
    rating: int = 0,
    rationale: str = "",
) -> dict[str, Any]:
    """Push a drafted review reply to managers for approval."""
    err = _require_token()
    if err:
        return err
    if not draft_text:
        return {"ok": False, "error": "draft_text required"}
    message = (
        f"Draft reply for review {review_id or '(unknown)'} "
        f"(rating {rating}/5):\n\n{draft_text}"
    )
    notify = await notify_managers(
        store_id=store_id or "",
        message=message,
        title="Review Response Draft",
        notification_type="REVIEW_DRAFT_RESPONSE",
        priority="HIGH" if rating and rating <= 2 else "MEDIUM",
        rationale=rationale,
    )
    proposal = _proposal(
        "DRAFT_REVIEW_REPLY",
        store_id or "",
        summary=f"Draft reply for review {review_id}",
        rationale=rationale or "Low-rating review requires manager-approved public reply",
        payload={"review_id": review_id, "rating": rating, "draft": draft_text[:2000]},
    )
    return {"ok": bool(notify.get("ok")), "proposal": proposal, "sent": notify.get("sent", 0)}


async def draft_kitchen_brief(
    store_id: str,
    brief_text: str,
    rationale: str = "",
) -> dict[str, Any]:
    """Notify managers/kitchen with a performance brief (no execute)."""
    notify = await notify_managers(
        store_id=store_id,
        message=brief_text,
        title="Kitchen Performance Brief",
        notification_type="KITCHEN_COACH_BRIEF",
        priority="MEDIUM",
        rationale=rationale,
    )
    proposal = _proposal(
        "DRAFT_KITCHEN_BRIEF",
        store_id,
        summary="Nightly kitchen brief",
        rationale=rationale or "Metrics-based coaching brief",
        payload={"brief_preview": (brief_text or "")[:300]},
    )
    return {"ok": bool(notify.get("ok")), "proposal": proposal, "sent": notify.get("sent", 0)}


async def write_forecast(
    store_id: str,
    forecasts: Optional[list] = None,
    rationale: str = "",
) -> dict[str, Any]:
    """
    Write forecast records via analytics API.
    Treated as PROPOSE-tier operational write (forecast table, not commercial execute).
    """
    err = _require_token()
    if err:
        return err
    forecasts = forecasts or []
    if not store_id or not forecasts:
        return {"ok": False, "error": "store_id and forecasts required"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        st, body = await post_json(
            client,
            "/api/analytics/forecast",
            {"storeId": store_id, "forecasts": forecasts, "generatedBy": "demand_forecast_agent"},
        )
        ok = st in (200, 201)
        proposal = _proposal(
            "WRITE_FORECAST",
            store_id,
            summary=f"Wrote {len(forecasts)} forecast row(s)",
            rationale=rationale or "WMA demand forecast",
            payload={"count": len(forecasts), "http_status": st},
        )
        return {"ok": ok, "proposal": proposal, "http_status": st}


# Registry for the ops LLM runner (name -> callable)
OPS_TOOL_FUNCTIONS: dict[str, Any] = {
    "list_stores": list_stores,
    "list_low_stock": list_low_stock,
    "get_forecast_snippet": get_forecast_snippet,
    "count_active_orders": count_active_orders,
    "count_recent_orders": count_recent_orders,
    "get_top_items": get_top_items,
    "get_slow_items": get_slow_items,
    "get_order_context": get_order_context,
    "read_churn_segment": read_churn_segment,
    "read_staff_slots": read_staff_slots,
    "read_kitchen_metrics": read_kitchen_metrics,
    "read_order_metrics": read_order_metrics,
    "read_inventory_levels": list_low_stock,  # alias
    "compute_pricing_signal": compute_pricing_signal,
    "compute_wma_forecast": compute_wma_forecast,
    "create_draft_po": create_draft_po,
    "draft_purchase_order": create_draft_po,  # alias
    "notify_managers": notify_managers,
    "notify_manager": notify_managers,  # alias
    "propose_price_suggestion": propose_price_suggestion,
    "suggest_price_adjustment": propose_price_suggestion,  # alias
    "create_draft_campaign": create_draft_campaign,
    "draft_churn_campaign": create_draft_campaign,
    "create_draft_shifts": create_draft_shifts,
    "draft_shift_roster": create_draft_shifts,
    "submit_review_draft_notification": submit_review_draft_notification,
    "draft_review_reply": submit_review_draft_notification,
    "draft_kitchen_brief": draft_kitchen_brief,
    "write_forecast": write_forecast,
}

# JSON-schema-ish parameter hints for LLM function declarations
OPS_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "list_stores": {"description": "List restaurant stores", "parameters": {"type": "object", "properties": {}}},
    "list_low_stock": {
        "description": "List low-stock inventory items. Pass store_id or empty for all stores.",
        "parameters": {
            "type": "object",
            "properties": {"store_id": {"type": "string"}},
        },
    },
    "get_forecast_snippet": {
        "description": "Get demand forecast numbers for a store (do not invent quantities).",
        "parameters": {
            "type": "object",
            "properties": {
                "store_id": {"type": "string"},
                "item_id": {"type": "string"},
                "hours": {"type": "integer"},
            },
            "required": ["store_id"],
        },
    },
    "count_active_orders": {
        "description": "Count active kitchen orders for a store",
        "parameters": {
            "type": "object",
            "properties": {"store_id": {"type": "string"}},
            "required": ["store_id"],
        },
    },
    "count_recent_orders": {
        "description": "Count recent orders in last N minutes",
        "parameters": {
            "type": "object",
            "properties": {
                "store_id": {"type": "string"},
                "minutes": {"type": "integer"},
            },
            "required": ["store_id"],
        },
    },
    "get_top_items": {
        "description": "Top selling menu items",
        "parameters": {
            "type": "object",
            "properties": {
                "store_id": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["store_id"],
        },
    },
    "get_slow_items": {
        "description": "Slow-moving menu items for discount candidates",
        "parameters": {
            "type": "object",
            "properties": {
                "store_id": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["store_id"],
        },
    },
    "get_order_context": {
        "description": "Fetch order line items for a review",
        "parameters": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    },
    "read_churn_segment": {
        "description": "List churned high-value customers for a store",
        "parameters": {
            "type": "object",
            "properties": {"store_id": {"type": "string"}},
            "required": ["store_id"],
        },
    },
    "read_staff_slots": {
        "description": "List schedulable staff for a store",
        "parameters": {
            "type": "object",
            "properties": {"store_id": {"type": "string"}},
            "required": ["store_id"],
        },
    },
    "read_kitchen_metrics": {
        "description": "Today kitchen metrics for coaching brief",
        "parameters": {
            "type": "object",
            "properties": {"store_id": {"type": "string"}},
            "required": ["store_id"],
        },
    },
    "read_order_metrics": {
        "description": "Order activity metrics for a store",
        "parameters": {
            "type": "object",
            "properties": {"store_id": {"type": "string"}},
        },
    },
    "compute_pricing_signal": {
        "description": "Compute overload/underload pricing signal from counts (deterministic)",
        "parameters": {
            "type": "object",
            "properties": {
                "store_id": {"type": "string"},
                "active_count": {"type": "integer"},
                "recent_count": {"type": "integer"},
                "current_hour": {"type": "integer"},
            },
            "required": ["store_id"],
        },
    },
    "compute_wma_forecast": {
        "description": "Compute weighted moving average forecast from a numeric series",
        "parameters": {
            "type": "object",
            "properties": {
                "series": {"type": "array", "items": {"type": "number"}},
                "weights": {"type": "array", "items": {"type": "number"}},
            },
            "required": ["series"],
        },
    },
    "create_draft_po": {
        "description": "Create a DRAFT purchase order (manager approval required). Never finalizes PO.",
        "parameters": {
            "type": "object",
            "properties": {
                "store_id": {"type": "string"},
                "supplier_id": {"type": "string"},
                "items": {"type": "array"},
                "rationale": {"type": "string"},
                "notes": {"type": "string"},
            },
            "required": ["store_id", "supplier_id", "items"],
        },
    },
    "notify_managers": {
        "description": "Notify store managers with a message including agent rationale",
        "parameters": {
            "type": "object",
            "properties": {
                "store_id": {"type": "string"},
                "message": {"type": "string"},
                "title": {"type": "string"},
                "notification_type": {"type": "string"},
                "priority": {"type": "string"},
                "rationale": {"type": "string"},
            },
            "required": ["store_id", "message"],
        },
    },
    "propose_price_suggestion": {
        "description": (
            "Suggest price change via manager notification only. "
            "NEVER patches menu. percent capped by system (12% increase / 15% discount)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "store_id": {"type": "string"},
                "direction": {"type": "string"},
                "percent": {"type": "number"},
                "item_ids": {"type": "array"},
                "item_names": {"type": "array"},
                "rationale": {"type": "string"},
                "active_count": {"type": "integer"},
                "recent_count": {"type": "integer"},
            },
            "required": ["store_id", "direction", "percent"],
        },
    },
    "create_draft_campaign": {
        "description": "Create DRAFT win-back campaign",
        "parameters": {
            "type": "object",
            "properties": {
                "store_id": {"type": "string"},
                "customer_ids": {"type": "array"},
                "message": {"type": "string"},
                "discount_percent": {"type": "number"},
                "rationale": {"type": "string"},
                "name": {"type": "string"},
            },
            "required": ["store_id", "customer_ids"],
        },
    },
    "create_draft_shifts": {
        "description": "Bulk create DRAFT shifts for manager review",
        "parameters": {
            "type": "object",
            "properties": {
                "store_id": {"type": "string"},
                "shifts": {"type": "array"},
                "rationale": {"type": "string"},
            },
            "required": ["store_id", "shifts"],
        },
    },
    "submit_review_draft_notification": {
        "description": "Send drafted review reply to managers for approval",
        "parameters": {
            "type": "object",
            "properties": {
                "store_id": {"type": "string"},
                "draft_text": {"type": "string"},
                "review_id": {"type": "string"},
                "rating": {"type": "integer"},
                "rationale": {"type": "string"},
            },
            "required": ["draft_text"],
        },
    },
    "draft_kitchen_brief": {
        "description": "Send kitchen coaching brief notification from metrics only",
        "parameters": {
            "type": "object",
            "properties": {
                "store_id": {"type": "string"},
                "brief_text": {"type": "string"},
                "rationale": {"type": "string"},
            },
            "required": ["store_id", "brief_text"],
        },
    },
    "write_forecast": {
        "description": "Write computed forecast rows to analytics API",
        "parameters": {
            "type": "object",
            "properties": {
                "store_id": {"type": "string"},
                "forecasts": {"type": "array"},
                "rationale": {"type": "string"},
            },
            "required": ["store_id", "forecasts"],
        },
    },
}
