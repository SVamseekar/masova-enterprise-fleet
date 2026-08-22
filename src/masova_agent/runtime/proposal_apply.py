"""
Applies approved ActionProposals against the demo SQLite database.
Active when DEMO_MODE=true.

Safety invariants:
- DRAFT_PURCHASE_ORDER -> updates purchase_orders.status to PENDING_APPROVAL and approved_by = 'demo-manager'
- DRAFT_CHURN_CAMPAIGN -> updates campaigns.status to SCHEDULED
- DRAFT_SHIFT_ROSTER -> updates staff_shifts.status to CONFIRMED
- SUGGEST_PRICE_ADJUSTMENT -> NEVER alters menu_items.price (advisory only)
"""

from __future__ import annotations

import logging
from typing import Any

from ..services.demo_backend import _connect, demo_mode

logger = logging.getLogger(__name__)


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
            if po_id:
                conn.execute(
                    "UPDATE purchase_orders SET status = 'PENDING_APPROVAL', approved_by = 'demo-manager' WHERE id = ?",
                    (po_id,),
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
            if camp_id:
                conn.execute("UPDATE campaigns SET status = 'SCHEDULED' WHERE id = ?", (camp_id,))
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
            if store_id:
                conn.execute(
                    "UPDATE staff_shifts SET status = 'CONFIRMED' WHERE store_id = ? AND status = 'DRAFT'",
                    (store_id,),
                )
            else:
                conn.execute("UPDATE staff_shifts SET status = 'CONFIRMED' WHERE status = 'DRAFT'")
            conn.commit()
            return True

        if ptype == "SUGGEST_PRICE_ADJUSTMENT":
            # Safety Invariant: Dynamic pricing suggestions are advisory and never mutate catalog prices.
            logger.info("Price suggestion proposal approved — recorded without mutating menu_items catalog price.")
            return True

        return False
    except Exception as e:
        logger.error("Failed to apply proposal %s: %s", proposal.get("proposal_id"), e)
        return False
    finally:
        conn.close()
