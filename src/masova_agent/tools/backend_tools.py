"""
MaSoVa backend API tools for the support agent.
Each function is registered as an ADK tool — Gemini calls them when needed.

Customer identity always comes from the verified JWT bound at the request
boundary (see auth.py / contextvars). LLM-supplied ids are never trusted for
ownership or outbound calls.
"""

import logging
import httpx
from ..auth import get_current_identity
from ..utils.config import get_config

logger = logging.getLogger(__name__)


def _headers() -> dict:
    """
    Build auth headers from the authenticated caller's identity.

    The agent always acts on-behalf-of the customer who is talking to it —
    never as a privileged role like MANAGER. Forwarding the customer's own
    verified JWT means the gateway's JwtAuthenticationFilter derives
    X-User-Id/X-User-Type from real claims, so every backend call is bound
    to the same identity checks (ownership, ACLs) a direct customer request
    would get.
    """
    identity = get_current_identity()
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {identity.raw_token}",
    }


def _base() -> str:
    return get_config().backend_url + "/api"


def _forbidden_user_message() -> str:
    """User-facing message for backend 403 — never leak raw API bodies."""
    return (
        "I'm not able to do that — this order doesn't belong to your account, "
        "or you don't have permission for that action."
    )


def _map_http_error(status_code: int) -> dict:
    if status_code == 403:
        return {"error": "forbidden", "message": _forbidden_user_message()}
    return {"error": f"HTTP {status_code}"}


def _get(path: str, params: dict | None = None) -> dict:
    try:
        r = httpx.get(f"{_base()}{path}", params=params, headers=_headers(), timeout=8.0)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        logger.warning("GET %s → %s", path, e.response.status_code)
        return _map_http_error(e.response.status_code)
    except Exception as e:
        logger.error("GET %s failed: %s", path, e)
        return {"error": str(e)}


def _post(path: str, body: dict) -> dict:
    try:
        r = httpx.post(f"{_base()}{path}", json=body, headers=_headers(), timeout=8.0)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        logger.warning("POST %s → %s", path, e.response.status_code)
        return _map_http_error(e.response.status_code)
    except Exception as e:
        logger.error("POST %s failed: %s", path, e)
        return {"error": str(e)}


def _format_error_reply(data: dict, fallback: str) -> str:
    if data.get("error") == "forbidden":
        return data.get("message", _forbidden_user_message())
    return fallback


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------

def get_order_status(order_id: str) -> str:
    """
    Retrieve the current status of a customer order.

    Args:
        order_id: The order ID (e.g. "6a1dac1881e32e63c4757801").

    Returns:
        Human-readable order status summary.
    """
    data = _get(f"/orders/{order_id}")
    if "error" in data:
        return _format_error_reply(
            data,
            f"Sorry, I couldn't find order {order_id}. Please double-check the order ID.",
        )

    status = data.get("status", "UNKNOWN")
    order_num = data.get("orderNumber", order_id)
    items = data.get("items", [])
    item_list = ", ".join(
        f"{i.get('quantity', 1)}x {i.get('name', '?')}" for i in items
    )
    eta = data.get("preparationTime", "")
    eta_str = f" (ETA: ~{eta} min)" if eta else ""
    customer = data.get("customerName", "")
    customer_str = f" for {customer}" if customer else ""

    status_messages = {
        "PENDING": "has been received and is pending confirmation",
        "RECEIVED": "has been confirmed and will be prepared shortly",
        "PREPARING": "is being prepared by the kitchen",
        "OVEN": "is in the oven",
        "BAKED": "is ready and waiting for dispatch",
        "DISPATCHED": "is out for delivery",
        "OUT_FOR_DELIVERY": "is out for delivery",
        "DELIVERED": "has been delivered",
        "COMPLETED": "is complete — thank you!",
        "SERVED": "has been served — enjoy your meal!",
        "CANCELLED": "has been cancelled",
    }
    desc = status_messages.get(status, f"is currently {status}")
    total = data.get("total", "")
    total_str = f" Total: €{total:.2f}." if isinstance(total, (int, float)) and total else ""
    return (
        f"Order #{order_num}{customer_str} {desc}{eta_str}.{total_str}\n"
        f"Items: {item_list or 'details unavailable'}."
    )


def get_menu_items(store_id: str, category: str = "") -> str:
    """
    Fetch available menu items for a store, optionally filtered by cuisine or category.

    Args:
        store_id: Store ID to query (e.g. "DOM001" or the MongoDB ID).
        category: Optional filter — cuisine (ITALIAN, AMERICAN, CONTINENTAL, BEVERAGES, DESSERTS)
                  or category (PIZZA, BURGER, etc.). Case-insensitive.

    Returns:
        Formatted list of menu items with prices.
    """
    data = _get("/menu", params={"storeId": store_id, "available": "true"})
    if "error" in data:
        return _format_error_reply(
            data,
            "Sorry, I couldn't fetch the menu right now. Please try again shortly.",
        )

    items = data if isinstance(data, list) else data.get("content", data.get("items", []))

    # Filter client-side by cuisine or category
    if category:
        cat_upper = category.upper()
        filtered = [
            i for i in items
            if cat_upper in (i.get("cuisine", "") or "").upper()
            or cat_upper in (i.get("category", "") or "").upper()
            or cat_upper in (i.get("name", "") or "").upper()
        ]
        items = filtered if filtered else items  # fall back to all if no match

    if not items:
        return "No menu items found at this store right now."

    lines = []
    for item in items[:12]:
        name = item.get("name", "Unknown")
        price = item.get("discountedPrice") or item.get("basePrice", 0)
        # Backend may return minor units (cents) or major units; large ints → cents.
        price_display = price / 100 if isinstance(price, (int, float)) and price > 100 else price
        desc = item.get("description", "")
        spice = item.get("spiceLevel", "")
        spice_str = f" [{spice}]" if spice and spice != "NONE" else ""
        desc_str = f" — {desc[:60]}" if desc else ""
        lines.append(f"• {name}{spice_str}: €{price_display:.2f}{desc_str}")

    total = len(items)
    more = f"\n...and {total - 12} more items." if total > 12 else ""
    cat_str = f" ({category})" if category else ""
    return f"Menu items{cat_str} at this store:\n" + "\n".join(lines) + more


def get_store_hours(store_id: str) -> str:
    """
    Get operating hours and status for a store.

    Args:
        store_id: The store ID (e.g. "DOM001" or MongoDB store ID).

    Returns:
        Store name, hours, and current open/closed status.
    """
    data = _get(f"/stores/{store_id}")
    if "error" in data:
        return _format_error_reply(
            data,
            "Sorry, I couldn't retrieve store information right now.",
        )

    name = data.get("name", f"Store {store_id}")
    # Support both flat (legacy) and nested operatingConfig shapes from the backend.
    config = data.get("operatingConfig") or {}
    open_time = data.get("openingTime") or config.get("openingTime", "N/A")
    close_time = data.get("closingTime") or config.get("closingTime", "N/A")
    if "isOpen" in data:
        is_open = bool(data.get("isOpen"))
        status_str = "currently OPEN" if is_open else "currently CLOSED"
    else:
        status = data.get("status", "UNKNOWN")
        is_active = status == "ACTIVE"
        status_str = "currently ACTIVE" if is_active else f"currently {status}"
    hours_str = f"\nHours: {open_time} – {close_time}" if open_time != "N/A" else ""
    currency = data.get("currency", "EUR")
    locale = data.get("locale", "")
    locale_str = f" ({locale})" if locale else ""
    return f"{name}{locale_str} is {status_str}.{hours_str} Currency: {currency}."


def submit_complaint(order_id: str, description: str) -> str:
    """
    Submit a complaint or support ticket for an order, on behalf of the
    customer currently chatting with the agent. Recorded for manager review —
    the agent does not take immediate remedial action.

    Args:
        order_id: The order ID the complaint relates to.
        description: Clear description of the issue (minimum 10 characters).

    Returns:
        Confirmation with ticket reference number.
    """
    if len(description.strip()) < 10:
        return "Please provide more detail about the issue so we can help you effectively."

    identity = get_current_identity()
    data = _post("/reviews/complaints", {
        "customerId": identity.user_id,
        "orderId": order_id,
        "description": description,
        "type": "COMPLAINT",
    })

    if "error" in data:
        return _format_error_reply(
            data,
            (
                "Your complaint has been noted. Our support team will contact you within 24 hours. "
                "You can also reach us at support@masova.com."
            ),
        )

    ticket_ref = data.get("id", data.get("ticketId", f"SUP-{order_id[-6:]}"))
    status = data.get("status", "")
    pending_note = (
        " It is pending manager review and has not been actioned yet."
        if str(status).upper() in ("PENDING", "PENDING_APPROVAL", "")
        else ""
    )
    return (
        f"Your complaint has been recorded for manager review. Ticket: {ticket_ref}.{pending_note} "
        f"We'll respond within 24 hours once it has been reviewed."
    )


def get_loyalty_points() -> str:
    """
    Get the loyalty points balance, tier, and next reward threshold for the
    customer currently chatting with the agent.

    Returns:
        A string describing the customer's loyalty points balance and tier level.
    """
    identity = get_current_identity()
    data = _get(f"/customers/{identity.user_id}")
    if "error" in data:
        return _format_error_reply(
            data,
            "I couldn't retrieve your loyalty points right now. Please check the MaSoVa app.",
        )

    points = data.get("loyaltyPoints") or data.get("points", 0) or 0
    tier = data.get("loyaltyTier") or data.get("tier", "BRONZE")
    name = data.get("name", "")
    name_str = f"{name}, you have" if name else "You have"

    thresholds = {"BRONZE": 500, "SILVER": 2000, "GOLD": 5000, "PLATINUM": 10000}
    next_tier_map = {"BRONZE": "SILVER", "SILVER": "GOLD", "GOLD": "PLATINUM", "PLATINUM": None}
    next_tier = next_tier_map.get(tier)
    if next_tier:
        needed = max(0, thresholds.get(next_tier, 0) - points)
        next_info = f" {needed} more points to reach {next_tier}." if needed > 0 else f" You're ready for {next_tier}!"
    else:
        next_info = " You're at the highest tier — PLATINUM!"

    total_orders = data.get("totalOrders", "")
    orders_str = f" ({total_orders} orders)" if total_orders else ""
    return f"{name_str} {points} loyalty points and are a {tier} member{orders_str}.{next_info}"


def get_store_wait_time(store_id: str) -> str:
    """
    Get the estimated current wait time at a store based on active orders.

    Args:
        store_id: The store's unique identifier (e.g. "DOM001").

    Returns:
        A string describing the estimated wait time for new orders.
    """
    data = _get("/orders", params={
        "storeId": store_id,
        "status": "RECEIVED,PREPARING,OVEN",
        "size": 1,
    })
    if "error" in data:
        return _format_error_reply(
            data,
            "I couldn't check the current wait time. Please call the store directly.",
        )

    active = data.get("totalElements", 0) if isinstance(data, dict) else len(data)

    if active == 0:
        return "Great news — the kitchen is currently free. Expect very fast service right now!"
    elif active <= 5:
        return f"The kitchen has {active} order(s) in progress. Estimated wait: 15–20 minutes."
    elif active <= 10:
        return f"The kitchen is moderately busy with {active} orders. Estimated wait: 25–35 minutes."
    else:
        return f"The kitchen is very busy right now ({active} active orders). Estimated wait: 40–50 minutes."


def cancel_order(order_id: str, reason: str) -> str:
    """
    Request cancellation of a customer order if it is still in a cancellable
    state (PENDING or RECEIVED). This submits a cancellation request for manager
    approval — the agent never cancels an order immediately.

    Args:
        order_id: The unique order identifier.
        reason: The reason for cancellation (must be at least 5 characters).

    Returns:
        Confirmation or explanation of why cancellation isn't possible.
    """
    if len(reason.strip()) < 5:
        return "Please provide a reason for cancellation (at least 5 characters)."

    order_data = _get(f"/orders/{order_id}")
    if "error" not in order_data:
        current_status = order_data.get("status", "")
        if current_status and current_status not in {"PENDING", "RECEIVED"}:
            return (
                f"Sorry, order #{order_id} cannot be cancelled — it is already {current_status}. "
                f"Orders can only be cancelled when PENDING or RECEIVED. "
                f"I can submit a complaint or refund request instead."
            )
    elif order_data.get("error") == "forbidden":
        return order_data.get("message", _forbidden_user_message())

    # Always go through the approval-gated endpoint — the agent requests
    # cancellation on the customer's behalf, a manager approves or rejects it.
    data = _post(f"/orders/{order_id}/cancel-request", {"reason": reason})
    if "error" in data:
        return _format_error_reply(
            data,
            f"I wasn't able to submit a cancellation request for order #{order_id} right now. "
            f"Please contact the restaurant directly.",
        )
    return (
        f"Your cancellation request for order #{order_id} has been submitted for manager review. "
        f"Reason: {reason}. The order is still active until a manager approves the cancellation."
    )


def request_refund(order_id: str, reason: str) -> str:
    """
    Request a refund for an order (pending manager approval; no money moves immediately).

    Args:
        order_id: The order ID to refund.
        reason: Reason for the refund request (at least 5 characters).

    Returns:
        Confirmation or guidance on next steps.
    """
    if len(reason.strip()) < 5:
        return "Please provide a reason for the refund request."

    data = _post("/payments/refund/request", {"orderId": order_id, "reason": reason})

    if "error" in data:
        return _format_error_reply(
            data,
            (
                "Your refund request has been logged. A specialist will review it and process "
                "within 3–5 business days. You'll receive an email confirmation."
            ),
        )

    refund_id = data.get("refundId", data.get("id", ""))
    status = str(data.get("status", "")).upper()
    ref_str = f" (Ref: {refund_id})" if refund_id else ""
    pending_note = (
        " It is pending manager approval — no refund has been processed yet."
        if status in ("PENDING_APPROVAL", "PENDING", "")
        else ""
    )
    return (
        f"Refund request submitted for order {order_id}{ref_str}.{pending_note} "
        f"If approved, processing takes 3–5 business days and we'll notify you by email."
    )
