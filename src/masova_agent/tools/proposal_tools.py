"""In-chat proposal list / approve / reject — same path as HTTP resolve."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def list_pending_proposals(store_id: str = "") -> dict[str, Any]:
    from ..runtime import proposal_store

    rows = proposal_store.list_proposals(
        store_id=store_id or None,
        status="PENDING",
        limit=100,
    )
    return {"ok": True, "proposals": rows, "count": len(rows)}


async def approve_proposal(proposal_id: str, note: str = "") -> dict[str, Any]:
    from ..runtime import proposal_store
    from ..runtime.proposal_apply import apply_approved_proposal

    pid = (proposal_id or "").strip()
    if not pid:
        return {"ok": False, "error": "proposal_id_required"}
    rec = proposal_store.get_proposal(pid)
    if not rec:
        return {"ok": False, "error": "proposal_not_found", "proposal_id": pid}
    if str(rec.get("status") or "").upper() != "PENDING":
        return {
            "ok": False,
            "error": "proposal_not_pending",
            "proposal_id": pid,
            "status": rec.get("status"),
        }
    try:
        updated = proposal_store.resolve_proposal(pid, "APPROVED", note=note or "")
    except ValueError as e:
        return {"ok": False, "error": str(e), "proposal_id": pid}
    if not updated:
        return {"ok": False, "error": "proposal_not_found", "proposal_id": pid}
    applied = apply_approved_proposal(updated)
    updated = dict(updated)
    updated["applied"] = applied
    updated["ok"] = True
    return updated


async def reject_proposal(proposal_id: str, note: str = "") -> dict[str, Any]:
    from ..runtime import proposal_store
    from ..runtime.proposal_apply import apply_rejected_proposal

    pid = (proposal_id or "").strip()
    if not pid:
        return {"ok": False, "error": "proposal_id_required"}
    rec = proposal_store.get_proposal(pid)
    if not rec:
        return {"ok": False, "error": "proposal_not_found", "proposal_id": pid}
    if str(rec.get("status") or "").upper() != "PENDING":
        return {
            "ok": False,
            "error": "proposal_not_pending",
            "proposal_id": pid,
            "status": rec.get("status"),
        }
    try:
        updated = proposal_store.resolve_proposal(pid, "REJECTED", note=note or "")
    except ValueError as e:
        return {"ok": False, "error": str(e), "proposal_id": pid}
    if not updated:
        return {"ok": False, "error": "proposal_not_found", "proposal_id": pid}
    applied = apply_rejected_proposal(updated, note=note or "")
    updated = dict(updated)
    updated["applied"] = applied
    updated["ok"] = True
    return updated
