"""
Single ops contract for demo SQLite AND the live MaSoVa platform.

Tools, agents, proposal store, and the console must not each reinterpret
money, names, time, churn, shifts, or HITL cards. Normalize here once.
"""

from __future__ import annotations

import re
from typing import Any, Optional

# --- Invariants (fleet-wide; not flagship-only) --------------------------------

LIVE_KITCHEN_STATUSES = ("RECEIVED", "PREPARING", "OVEN", "BAKED", "READY")
CLOSED_ORDER_STATUSES = ("DELIVERED", "COMPLETED", "SERVED")

# Canonical service windows for every store.
SHIFT_WINDOWS = {
    "morning": ("09:00", "16:00", "Morning"),
    "mid": ("11:00", "19:00", "Mid"),
    "midday": ("11:00", "19:00", "Mid"),
    "afternoon": ("16:00", "23:00", "Afternoon"),
    "evening": ("16:00", "23:00", "Evening"),
}

CHURN_MIN_ORDERS = 2
CHURN_INACTIVE_DAYS = 14
CHURN_LOOKBACK_DAYS = 60

SIDE_EFFECT_TYPES = frozenset({"NOTIFY_MANAGERS"})
SNAPSHOT_AGENTS = frozenset({
    "inventory_reorder",
    "demand_forecast",
    "shift_optimisation",
    "kitchen_coach",
    "dynamic_pricing",
    "churn_prevention",
})
DECISION_TYPES = frozenset({
    "DRAFT_PURCHASE_ORDER",
    "WRITE_FORECAST",
    "DRAFT_SHIFT_ROSTER",
    "DRAFT_KITCHEN_BRIEF",
    "DRAFT_REVIEW_REPLY",
    "DRAFT_CHURN_CAMPAIGN",
    "SUGGEST_PRICE_ADJUSTMENT",
})
LOW_STOCK_TOOLS = frozenset({"list_low_stock", "read_inventory_levels"})

PRICE_INCREASE_PCT_MAX = 12
PRICE_DISCOUNT_PCT_MAX = 15
OVERLOAD_ACTIVE_ORDERS = 15
UNDERLOAD_ORDERS_30MIN = 3
RECOVERY_DISCOUNT_PERCENT = 15
SLOW_TICKET_MINUTES = 22
DEMAND_BUFFER = 1.05
PO_QTY_MAX_MULT = 2.0


def clamp_po_quantity(requested: Any, reorder: Any, *, current: Any = None, minimum: Any = None) -> float:
    """SKU restock qty. Never use store-level cover forecasts (e.g. 92 → 95)."""
    ro = _num(reorder) or 10.0
    if ro < 1:
        ro = 10.0
    req = _num(requested)
    if req is None or req < 1:
        return ro
    cap = ro * PO_QTY_MAX_MULT
    if req > cap:
        return ro
    return req


def shift_end_for(start: str, default: str = "16:00") -> str:
    mapping = {v[0]: v[1] for v in SHIFT_WINDOWS.values()}
    mapping.setdefault("08:00", "14:00")
    return mapping.get(str(start or ""), default)


def public_contract() -> dict[str, Any]:
    """JSON the console (and any client) can use instead of hardcoded windows."""
    windows = []
    seen: set[str] = set()
    for start, end, label in SHIFT_WINDOWS.values():
        key = f"{start}-{end}"
        if key in seen:
            continue
        seen.add(key)
        windows.append({"start": start, "end": end, "label": label})
    return {
        "shift_windows": windows,
        "churn": {
            "min_orders": CHURN_MIN_ORDERS,
            "inactive_days": CHURN_INACTIVE_DAYS,
            "lookback_days": CHURN_LOOKBACK_DAYS,
            "discount_percent": RECOVERY_DISCOUNT_PERCENT,
        },
        "pricing": {
            "increase_pct_max": PRICE_INCREASE_PCT_MAX,
            "discount_pct_max": PRICE_DISCOUNT_PCT_MAX,
            "overload_active_orders": OVERLOAD_ACTIVE_ORDERS,
            "underload_orders_30min": UNDERLOAD_ORDERS_30MIN,
        },
        "kitchen": {
            "live_statuses": list(LIVE_KITCHEN_STATUSES),
            "closed_statuses": list(CLOSED_ORDER_STATUSES),
            "slow_ticket_minutes": SLOW_TICKET_MINUTES,
        },
        "demand_buffer": DEMAND_BUFFER,
        "decision_types": sorted(DECISION_TYPES),
        "side_effect_types": sorted(SIDE_EFFECT_TYPES),
        "snapshot_agents": sorted(SNAPSHOT_AGENTS),
    }

_BLANK_NAMES = {"", "unknown", "item", "none", "null", "?", "n/a"}


def _first_str(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text.lower() not in _BLANK_NAMES:
            return text
    return ""


def _num(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def is_decision_card(rec: dict[str, Any] | None) -> bool:
    return str((rec or {}).get("type") or "") in DECISION_TYPES


def is_side_effect(rec: dict[str, Any] | None) -> bool:
    return str((rec or {}).get("type") or "") in SIDE_EFFECT_TYPES


# --- Money / catalog ----------------------------------------------------------

def unit_price_cents(row: dict[str, Any] | None) -> Optional[int]:
    """Menu/unit price in minor units. Never a line total (price × qty)."""
    if not isinstance(row, dict):
        return None
    explicit = _num(
        row.get("unit_price_cents")
        or row.get("unitPriceCents")
        or row.get("basePrice")
        or row.get("base_price")
    )
    if explicit is not None and explicit >= 0:
        if explicit >= 50 or float(explicit).is_integer():
            return int(round(explicit))
        return int(round(explicit * 100))

    unit = _num(row.get("unit_price") if row.get("unit_price") is not None else row.get("unitPrice"))
    qty = _num(row.get("quantity") or row.get("qty")) or 1.0
    raw_price = _num(row.get("price") if row.get("price") is not None else row.get("currentPrice"))

    if unit is not None:
        if unit >= 50:
            return int(round(unit))
        return int(round(unit * 100))
    if raw_price is None:
        return None
    if qty > 1:
        raw_price = raw_price / qty
    if raw_price >= 50:
        return int(round(raw_price))
    return int(round(raw_price * 100))


def catalog_name(row: dict[str, Any] | None) -> str:
    if not isinstance(row, dict):
        return ""
    return _first_str(
        row.get("item_name"),
        row.get("itemName"),
        row.get("name"),
        row.get("menuItemName"),
        row.get("skuName"),
    )


def catalog_row(row: dict[str, Any] | None) -> dict[str, Any]:
    src = row if isinstance(row, dict) else {}
    cents = unit_price_cents(src)
    return {
        "id": src.get("id") or src.get("menuItemId") or src.get("menu_item_id"),
        "name": catalog_name(src),
        "price": cents,
        "unit_price_cents": cents,
        "volume": src.get("volume") or src.get("orderCount") or src.get("unitsSold"),
    }


def merge_menu_prices(items: list[Any], menu_rows: list[Any]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for raw in menu_rows or []:
        if not isinstance(raw, dict):
            continue
        row = catalog_row(raw)
        if row["id"] is not None:
            by_id[str(row["id"])] = row
    out: list[dict[str, Any]] = []
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        row = catalog_row(raw)
        menu = by_id.get(str(row["id"])) if row["id"] is not None else None
        if menu:
            if menu.get("name"):
                row["name"] = menu["name"]
            if menu.get("unit_price_cents") is not None:
                row["price"] = menu["unit_price_cents"]
                row["unit_price_cents"] = menu["unit_price_cents"]
        out.append(row)
    return out


def inventory_row(row: dict[str, Any], store_id: str = "") -> dict[str, Any]:
    src = row if isinstance(row, dict) else {}
    return {
        "id": src.get("id"),
        "store_id": store_id or src.get("store_id") or src.get("storeId") or "",
        "item_name": catalog_name(src),
        "current_stock": src.get("currentStock") or src.get("current_stock") or src.get("quantity"),
        "minimum_stock": src.get("minimumStock") if src.get("minimumStock") is not None else src.get("minimum_stock"),
        "reorder_quantity": src.get("reorderQuantity", src.get("reorder_quantity", 10)),
        "unit_cost": src.get("unitCost", src.get("unit_cost", 0)),
        "primary_supplier_id": src.get("primarySupplierId") or src.get("primary_supplier_id") or src.get("supplierId"),
        "unit": src.get("unit") or src.get("uom") or "",
    }


# --- Demand / kitchen ---------------------------------------------------------

def demand_series(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {"series": [], "series_days": []}
    series = body.get("series")
    days = body.get("series_days") or body.get("days") or []
    if not isinstance(series, list) or not series:
        return {"series": [], "series_days": []}
    nums: list[float] = []
    for x in series:
        n = _num(x if not isinstance(x, dict) else (x.get("count") or x.get("orders") or x.get("qty")))
        if n is None:
            return {"series": [], "series_days": []}
        nums.append(n)
    return {
        "series": nums,
        "series_days": [str(d) for d in days][: len(nums)],
    }


def kitchen_metrics_row(body: Any, store_id: str = "") -> dict[str, Any]:
    m = body if isinstance(body, dict) else {}
    return {
        "ok": True,
        "store_id": store_id,
        "avg_prep_minutes": m.get("avgPrepTimeMinutes") or m.get("avgPrepMinutes"),
        "ticket_count": m.get("ticketCount") or m.get("orderCount") or 0,
        "slow_tickets": m.get("slowTickets") or 0,
        "period": m.get("period") or "today",
        "period_date": m.get("periodDate") or m.get("period_date"),
    }


def parse_kitchen_brief(text: str) -> dict[str, Any]:
    preview = str(text or "")
    def _m(pat: str) -> Optional[str]:
        hit = re.search(pat, preview, re.I)
        return hit.group(1) if hit else None
    return {
        "ticket_count": _m(r"Total Tickets:\s*([0-9.]+)") or _m(r"(\d+)\s*tickets"),
        "avg_prep_minutes": _m(r"Average Prep Time:\s*([0-9.]+)") or _m(r"([0-9.]+)\s*min"),
        "slow_tickets": _m(r"Slow Tickets:\s*([0-9.]+)") or _m(r"(\d+)\s*slow"),
        "period_date": _m(r"(\d{4}-\d{2}-\d{2})"),
        "brief_preview": preview[:300],
    }


# --- Churn / staff / shifts ---------------------------------------------------

def churn_customer_row(row: dict[str, Any]) -> dict[str, Any]:
    src = row if isinstance(row, dict) else {}
    stats = src.get("orderStats") if isinstance(src.get("orderStats"), dict) else {}
    return {
        "id": src.get("id"),
        "name": _first_str(src.get("name"), src.get("firstName"), "customer") or "customer",
        "last_order_at": src.get("lastOrderAt") or src.get("last_order_at") or src.get("lastOrderDate"),
        "order_count_60d": src.get("orderCount") or stats.get("totalOrders"),
    }


def shift_hhmm(value: Any, default: str = "") -> str:
    raw = str(value or "").strip()
    if not raw:
        return default
    if "T" in raw:
        return raw.split("T", 1)[1][:5] or default
    return raw[:5] if len(raw) >= 4 else default


def normalize_shift_row(
    raw: dict[str, Any],
    store_id: str,
    staff_index: Optional[dict[str, dict[str, Any]]] = None,
) -> dict[str, Any]:
    staff_index = staff_index or {}
    sid = raw.get("staffId") or raw.get("userId") or raw.get("employeeId") or raw.get("staff_id")
    rec = staff_index.get(str(sid)) if sid else None
    name = _first_str(
        raw.get("name"), raw.get("staffName"), raw.get("staff_name"), (rec or {}).get("name")
    ) or "Staff"
    role = raw.get("role") or raw.get("type") or (rec or {}).get("role") or "KITCHEN_STAFF"
    start = shift_hhmm(raw.get("startTime") or raw.get("start_time") or raw.get("startAt"))
    end = shift_hhmm(raw.get("endTime") or raw.get("end_time") or raw.get("endAt"))
    slot = str(raw.get("slotName") or raw.get("slot") or raw.get("window") or "").lower()
    slot_name = str(raw.get("slotName") or "")
    if (not start or not end) and slot:
        for key, (st, en, label) in SHIFT_WINDOWS.items():
            if key in slot:
                start = start or st
                end = end or en
                slot_name = slot_name or label
                break
    if start and not end:
        end = {v[0]: v[1] for v in SHIFT_WINDOWS.values()}.get(start, "16:00")
    if not start:
        start, end = "09:00", end or "16:00"
    date = str(raw.get("date") or "")
    if not date:
        for key in (raw.get("startAt"), raw.get("startTime")):
            if key and str(key)[:10].count("-") == 2:
                date = str(key)[:10]
                break
    if not slot_name:
        reverse = {v[0]: v[2] for v in SHIFT_WINDOWS.values()}
        slot_name = reverse.get(start, "")
    return {
        **raw,
        "storeId": raw.get("storeId") or store_id,
        "staffId": sid or raw.get("staffId"),
        "userId": sid or raw.get("userId"),
        "employeeId": sid or raw.get("employeeId"),
        "name": name,
        "staffName": name,
        "role": role,
        "date": date,
        "startTime": start,
        "endTime": end,
        "slotName": slot_name,
        "status": "DRAFT",
    }


def dedupe_shifts(shifts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple] = set()
    unique: list[dict[str, Any]] = []
    for row in shifts:
        if not isinstance(row, dict):
            continue
        key = (
            str(row.get("date") or ""),
            str(row.get("staffId") or row.get("staff_id") or row.get("staffName") or ""),
            str(row.get("startTime") or row.get("start_time") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


# --- Hydrate propose args from prior reads ------------------------------------

def _ids_from_prior(
    prior: list[dict[str, Any]],
    tools: set[str],
    list_key: str,
    id_key: str = "id",
) -> list[str]:
    for tr in reversed(prior or []):
        if str(tr.get("tool") or "") not in tools:
            continue
        body = tr.get("result") if isinstance(tr.get("result"), dict) else {}
        ids = []
        for row in body.get(list_key) or []:
            if isinstance(row, dict) and row.get(id_key):
                ids.append(str(row[id_key]))
        if ids:
            return ids
    return []


def hydrate_propose_args(
    tool_name: str,
    args: dict[str, Any],
    prior_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Fill required IDs/series from earlier reads. Same for every agent/store."""
    pinned = dict(args or {})
    name = str(tool_name or "")
    if name in ("create_draft_campaign", "draft_churn_campaign"):
        if not pinned.get("customer_ids"):
            pinned["customer_ids"] = _ids_from_prior(
                prior_results, {"read_churn_segment"}, "customers"
            )
    if name in ("create_draft_po", "draft_purchase_order"):
        if not pinned.get("items"):
            for tr in reversed(prior_results or []):
                if str(tr.get("tool") or "") in LOW_STOCK_TOOLS:
                    body = tr.get("result") if isinstance(tr.get("result"), dict) else {}
                    pinned["items"] = list(body.get("items") or [])
                    break
        if not pinned.get("supplier_id"):
            for it in pinned.get("items") or []:
                if isinstance(it, dict) and (
                    it.get("primary_supplier_id") or it.get("supplier_id") or it.get("supplierId")
                ):
                    pinned["supplier_id"] = (
                        it.get("primary_supplier_id") or it.get("supplier_id") or it.get("supplierId")
                    )
                    break
    if name in ("write_forecast",):
        wma: dict[str, Any] | None = None
        history: dict[str, Any] | None = None
        for tr in reversed(prior_results or []):
            body = tr.get("result") if isinstance(tr.get("result"), dict) else {}
            if not isinstance(body, dict):
                continue
            if wma is None and body.get("forecast") is not None:
                wma = body
            hist = demand_series(body)
            if history is None and hist["series"]:
                history = {**body, **hist}
        series = (wma or {}).get("series") or (history or {}).get("series") or []
        series_days = (wma or {}).get("series_days") or (history or {}).get("series_days") or []
        if not pinned.get("forecasts") and wma is not None:
            pinned["forecasts"] = [{
                "predicted_qty": wma.get("forecast"),
                "method": wma.get("method"),
                "n": wma.get("n"),
                "series": series,
                "series_days": series_days,
            }]
        elif pinned.get("forecasts") and series:
            first = pinned["forecasts"][0] if pinned["forecasts"] else None
            if isinstance(first, dict) and not first.get("series"):
                first = dict(first)
                first["series"] = series
                first["series_days"] = series_days
                pinned["forecasts"] = [first] + list(pinned["forecasts"][1:])
    if name in ("draft_kitchen_brief",):
        for tr in reversed(prior_results or []):
            if str(tr.get("tool") or "") != "read_kitchen_metrics":
                continue
            body = tr.get("result") if isinstance(tr.get("result"), dict) else {}
            for key in ("ticket_count", "avg_prep_minutes", "slow_tickets", "period_date"):
                if pinned.get(key) in (None, "") and body.get(key) not in (None, ""):
                    pinned[key] = body.get(key)
            if not pinned.get("brief_text"):
                pinned["brief_text"] = (
                    f"Kitchen metrics for {body.get('period_date') or 'last service'}: "
                    f"Total Tickets: {body.get('ticket_count')} "
                    f"Average Prep Time: {body.get('avg_prep_minutes')} "
                    f"Slow Tickets: {body.get('slow_tickets')}"
                )
            break
    if name in ("propose_price_suggestion", "suggest_price_adjustment"):
        if not pinned.get("item_ids") and not pinned.get("item_names"):
            tools = {"get_top_items"} if str(pinned.get("direction") or "").lower() == "increase" else {"get_slow_items", "get_top_items"}
            names: list[str] = []
            ids: list[str] = []
            for tr in reversed(prior_results or []):
                if str(tr.get("tool") or "") not in tools:
                    continue
                body = tr.get("result") if isinstance(tr.get("result"), dict) else {}
                for row in body.get("items") or []:
                    if isinstance(row, dict):
                        if row.get("id"):
                            ids.append(str(row["id"]))
                        if row.get("name"):
                            names.append(str(row["name"]))
                if ids or names:
                    break
            pinned.setdefault("item_ids", ids)
            pinned.setdefault("item_names", names)
    return pinned


def skip_incomplete_propose(
    tool_name: str,
    args: dict[str, Any],
    prior_results: list[dict[str, Any]] | None = None,
) -> Optional[dict[str, Any]]:
    """Skip cleanly instead of posting empty campaigns/POs/forecasts."""
    name = str(tool_name or "")
    empty_churn = {"ok": True, "skipped": True, "reason": "no_churn_customers", "proposal": None}

    def _churn_empty() -> bool:
        for tr in reversed(prior_results or []):
            if str(tr.get("tool") or "") != "read_churn_segment":
                continue
            body = tr.get("result") if isinstance(tr.get("result"), dict) else {}
            return int(body.get("count") or 0) == 0
        return False

    if name in ("create_draft_campaign", "draft_churn_campaign"):
        if not args.get("customer_ids") or _churn_empty():
            return empty_churn
    if name in ("create_draft_po", "draft_purchase_order") and not args.get("items"):
        return {"ok": True, "skipped": True, "reason": "no_po_items", "proposal": None}
    if name in ("write_forecast",) and not args.get("forecasts"):
        return {"ok": True, "skipped": True, "reason": "no_forecasts", "proposal": None}
    if name in ("create_draft_shifts", "draft_shift_roster") and not args.get("shifts"):
        return {"ok": True, "skipped": True, "reason": "no_shifts", "proposal": None}
    if name in ("notify_managers", "notify_manager") and _churn_empty():
        return empty_churn
    return None


# --- Seal proposal payloads for the console -----------------------------------

def seal_proposal_payload(type_: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    sealed = dict(payload or {})
    kind = str(type_ or "")
    if kind == "WRITE_FORECAST":
        forecasts = sealed.get("forecasts") or []
        first = forecasts[0] if forecasts and isinstance(forecasts[0], dict) else {}
        hist = demand_series(sealed) if sealed.get("series") else demand_series(first)
        if not hist["series"]:
            hist = demand_series(first)
        sealed["series"] = hist["series"] or list(sealed.get("series") or first.get("series") or [])
        sealed["series_days"] = hist["series_days"] or list(
            sealed.get("series_days") or first.get("series_days") or []
        )
        if sealed.get("predicted_qty") is None:
            sealed["predicted_qty"] = first.get("predicted_qty") or first.get("predictedQuantity")
        if not sealed.get("day"):
            sealed["day"] = first.get("day") or first.get("date")
    if kind == "SUGGEST_PRICE_ADJUSTMENT":
        items = sealed.get("items") or []
        sealed["items"] = [
            {**item, "currentPrice": catalog_row(item).get("unit_price_cents")}
            if isinstance(item, dict)
            else item
            for item in items
        ]
    if kind == "DRAFT_KITCHEN_BRIEF":
        parsed = parse_kitchen_brief(str(sealed.get("brief_preview") or ""))
        for key, val in parsed.items():
            if val and not sealed.get(key):
                sealed[key] = val
    if kind == "DRAFT_SHIFT_ROSTER":
        items = sealed.get("items") or []
        normed = [
            normalize_shift_row(it, str(sealed.get("store_id") or it.get("storeId") or ""))
            for it in items
            if isinstance(it, dict)
        ]
        sealed["items"] = dedupe_shifts(normed)
        sealed["shift_count"] = len(sealed["items"])
    if kind == "DRAFT_PURCHASE_ORDER":
        rows = []
        for it in sealed.get("items") or []:
            if not isinstance(it, dict):
                continue
            rec = inventory_row(it)
            rec["itemName"] = rec["item_name"] or it.get("itemName")
            rec["quantity"] = it.get("quantity") or rec.get("reorder_quantity")
            rows.append({**it, **rec})
        sealed["items"] = rows
    if kind == "DRAFT_CHURN_CAMPAIGN":
        ids = sealed.get("customer_ids") or sealed.get("targetUserIds") or []
        sealed["customer_ids"] = [str(x) for x in ids if x]
        sealed["customer_count"] = sealed.get("customer_count") or len(sealed["customer_ids"])
    if kind in SIDE_EFFECT_TYPES:
        sealed["side_effect"] = True
    return sealed
