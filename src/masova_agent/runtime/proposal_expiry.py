"""
Auto-expiry job for stale ActionProposals.
Sweeps proposals older than max_age_hours (default 72h) in PENDING status
and marks them EXPIRED.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import proposal_store

logger = logging.getLogger(__name__)


def sweep_expired(max_age_hours: int = 72) -> int:
    """
    Sweep pending proposals older than max_age_hours and resolve them as EXPIRED.
    Returns the count of expired proposals.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

    pending = proposal_store.list_proposals(status="PENDING", limit=500)
    expired_count = 0

    for p in pending:
        created_at_str = p.get("created_at")
        if not created_at_str:
            continue
        try:
            created_dt = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=timezone.utc)
            if created_dt <= cutoff:
                pid = p["proposal_id"]
                proposal_store.resolve_proposal(
                    pid,
                    "EXPIRED",
                    note=f"Auto-expired: exceeded {max_age_hours}h pending threshold",
                )
                expired_count += 1
                logger.info("Auto-expired proposal %s (created %s)", pid, created_at_str)
        except Exception as e:
            logger.warning("Failed to evaluate proposal expiry for %s: %s", p.get("proposal_id"), e)

    return expired_count
