"""
Applies approved ActionProposals against the demo SQLite database.
Active when DEMO_MODE=true.

Safety invariants:
- DRAFT_PURCHASE_ORDER -> updates purchase_orders.status to PENDING_APPROVAL and approved_by = 'demo-manager'
- DRAFT_CHURN_CAMPAIGN -> updates campaigns.status to SCHEDULED
- DRAFT_SHIFT_ROSTER -> updates staff_shifts.status to CONFIRMED
- SUGGEST_PRICE_ADJUSTMENT -> capped menu_items.price updates (12% / 15%)
- WRITE_FORECAST / DRAFT_REVIEW_REPLY / DRAFT_KITCHEN_BRIEF -> manager_actions rows
"""

from __future__ import annotations

import logging
from typing import Any

import json
import uuid
from datetime import datetime, timezone

from ..services.demo_backend import _connect, demo_mode, ensure_allowlisted_table
from ..tools.ops_tools import PRICE_DISCOUNT_PCT_MAX, PRICE_INCREASE_PCT_MAX

logger = logging.getLogger(__name__)

_MANAGER_ACTION_TYPES = {
    "WRITE_FORECAST",
    "DRAFT_REVIEW_REPLY",
    "DRAFT_KITCHEN_BRIEF",
}


def _ensure_manager_actions(conn) -> None:
    ensure_allowlisted_table(conn, "manager_actions")


def apply_approved_proposal(proposal: dict[str, Any]) -> bool:
    """Apply an approved ActionProposal against the demo database."""
    if not demo_mode():
        return False

    ptype = proposal.get("type", "")
    store_id = proposal.get("store_id", "")
    payload = proposal.get("payload") or {}

    try:
        conn = _connect()
    except Exception as e:
        logger.warning("Could not connect to demo DB to apply proposal: %s", e)
        return False

    try:
        if ptype == "DRAFT_PURCHASE_ORDER":
            po_id = payload.get("po_id") or payload.get("id")
            if po_id and store_id:
                conn.execute(
                    "UPDATE purchase_orders SET status = 'PENDING_APPROVAL', approved_by = 'demo-manager' "
                    "WHERE id = ? AND store_id = ?",
                    (po_id, store_id),
                )
            elif store_id:
                # Update most recent DRAFT PO for store
                conn.execute(
                    """
                    UPDATE purchase_orders SET status = 'PENDING_APPROVAL', approved_by = 'demo-manager'
                    WHERE id = (
                        SELECT id FROM purchase_orders
                        WHERE store_id = ? AND status = 'DRAFT'
                        ORDER BY created_at DESC LIMIT 1
                    )
                    """,
                    (store_id,),
                )
            conn.commit()
            return True

        if ptype == "DRAFT_CHURN_CAMPAIGN":
            camp_id = payload.get("campaign_id") or payload.get("id")
            if camp_id and store_id:
                conn.execute(
                    "UPDATE campaigns SET status = 'SCHEDULED' WHERE id = ? AND store_id = ?",
                    (camp_id, store_id),
                )
            elif store_id:
                conn.execute(
                    """
                    UPDATE campaigns SET status = 'SCHEDULED'
                    WHERE id = (
                        SELECT id FROM campaigns
                        WHERE store_id = ? AND status = 'DRAFT'
                        ORDER BY created_at DESC LIMIT 1
                    )
                    """,
                    (store_id,),
                )
            conn.commit()
            return True

        if ptype == "DRAFT_SHIFT_ROSTER":
            if not store_id:
                return False
            conn.execute(
                "UPDATE staff_shifts SET status = 'CONFIRMED' WHERE store_id = ? AND status = 'DRAFT'",
                (store_id,),
            )
            conn.commit()
            return True

        if ptype == "SUGGEST_PRICE_ADJUSTMENT":
            item_ids = payload.get("item_ids") or []
            try:
                percent = abs(float(payload.get("percent") or 0))
            except (TypeError, ValueError):
                percent = 0.0
            direction = str(payload.get("direction") or "").lower()
            if direction == "increase":
                percent = min(percent, PRICE_INCREASE_PCT_MAX)
                factor = 1 + percent / 100.0
            else:
                percent = min(percent, PRICE_DISCOUNT_PCT_MAX)
                factor = 1 - percent / 100.0
            for item_id in item_ids:
                row = conn.execute(
                    "SELECT price FROM menu_items WHERE id = ?",
                    (item_id,),
                ).fetchone()
                if not row:
                    continue
                new_price = round(float(row["price"]) * factor, 2)
                conn.execute(
                    "UPDATE menu_items SET price = ? WHERE id = ?",
                    (new_price, item_id),
                )
            conn.commit()
            return True

        if ptype in _MANAGER_ACTION_TYPES:
            _ensure_manager_actions(conn)
            conn.execute(
                """
                INSERT INTO manager_actions (id, store_id, type, status, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    store_id,
                    ptype,
                    "APPROVED",
                    json.dumps(payload, default=str),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
            return True

        return False
    except Exception as e:
        logger.error("Failed to apply proposal %s: %s", proposal.get("proposal_id"), e)
        return False
    finally:
        conn.close()


def apply_rejected_proposal(proposal: dict[str, Any], note: str = "") -> bool:
    """Apply a rejected ActionProposal against the demo database (cancel draft / record rejection reason)."""
    if not demo_mode():
        return False

    ptype = proposal.get("type", "")
    store_id = proposal.get("store_id", "")
    payload = proposal.get("payload") or {}
    reason = note or proposal.get("resolution_note") or "Rejected by manager"

    try:
        conn = _connect()
    except Exception as e:
        logger.warning("Could not connect to demo DB to apply proposal rejection: %s", e)
        return False

    try:
        if ptype == "DRAFT_PURCHASE_ORDER":
            po_id = payload.get("po_id") or payload.get("id")
            if po_id and store_id:
                conn.execute(
                    "UPDATE purchase_orders SET status = 'CANCELLED', rejection_reason = ? "
                    "WHERE id = ? AND store_id = ?",
                    (reason, po_id, store_id),
                )
            elif store_id:
                conn.execute(
                    """
                    UPDATE purchase_orders SET status = 'CANCELLED', rejection_reason = ?
                    WHERE id = (
                        SELECT id FROM purchase_orders
                        WHERE store_id = ? AND status = 'DRAFT'
                        ORDER BY created_at DESC LIMIT 1
                    )
                    """,
                    (reason, store_id),
                )
            conn.commit()
            return True

        if ptype == "DRAFT_CHURN_CAMPAIGN":
            camp_id = payload.get("campaign_id") or payload.get("id")
            if camp_id and store_id:
                conn.execute(
                    "UPDATE campaigns SET status = 'CANCELLED' WHERE id = ? AND store_id = ?",
                    (camp_id, store_id),
                )
            elif store_id:
                conn.execute(
                    """
                    UPDATE campaigns SET status = 'CANCELLED'
                    WHERE id = (
                        SELECT id FROM campaigns
                        WHERE store_id = ? AND status = 'DRAFT'
                        ORDER BY created_at DESC LIMIT 1
                    )
                    """,
                    (store_id,),
                )
            conn.commit()
            return True

        if ptype == "DRAFT_SHIFT_ROSTER":
            if not store_id:
                return False
            conn.execute(
                "UPDATE staff_shifts SET status = 'CANCELLED' WHERE store_id = ? AND status = 'DRAFT'",
                (store_id,),
            )
            conn.commit()
            return True

        if ptype == "SUGGEST_PRICE_ADJUSTMENT":
            logger.info("Price suggestion proposal rejected — menu_items catalog price untouched.")
            return True

        return False
    except Exception as e:
        logger.error("Failed to apply rejection for proposal %s: %s", proposal.get("proposal_id"), e)
        return False
    finally:
        conn.close()

