"""
Durable ActionProposal storage (v1).

Primary: in-memory + append-only JSONL under data/proposals/ (gitignored).
Optional: mirror to Redis when available.

This service does NOT execute approvals against commerce — resolve only records
manager outcome so ops can audit. Platform UI/backend remains source of truth
for final PO send, price PATCH, campaign go-live, etc.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Optional

from .models import ActionProposal, ProposalStatus, _utc_now_iso

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_by_id: dict[str, dict[str, Any]] = {}


def _data_dir() -> Path:
    root = os.getenv("PROPOSAL_DATA_DIR")
    if root:
        return Path(root)
    # repo-relative data/ (gitignored)
    return Path(__file__).resolve().parents[3] / "data" / "proposals"


def _jsonl_path() -> Path:
    return _data_dir() / "proposals.jsonl"


def save_proposal(proposal: ActionProposal | dict[str, Any]) -> dict[str, Any]:
    if isinstance(proposal, ActionProposal):
        rec = proposal.to_dict()
    else:
        rec = ActionProposal.from_dict(proposal).to_dict()
    pid = rec["proposal_id"]
    with _lock:
        _by_id[pid] = rec
        try:
            d = _data_dir()
            d.mkdir(parents=True, exist_ok=True)
            with open(_jsonl_path(), "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, default=str) + "\n")
        except Exception as e:
            logger.warning("proposal file append failed: %s", e)
    return rec


def get_proposal(proposal_id: str) -> Optional[dict[str, Any]]:
    with _lock:
        hit = _by_id.get(proposal_id)
        if hit:
            return dict(hit)
    # reload from file if memory cold
    _load_file_once()
    with _lock:
        hit = _by_id.get(proposal_id)
        return dict(hit) if hit else None


def list_proposals(
    *,
    store_id: Optional[str] = None,
    status: Optional[str] = None,
    agent: Optional[str] = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    _load_file_once()
    with _lock:
        rows = list(_by_id.values())
    if store_id:
        rows = [r for r in rows if r.get("store_id") == store_id]
    if status:
        rows = [r for r in rows if str(r.get("status")) == status]
    if agent:
        rows = [r for r in rows if r.get("agent") == agent]
    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return rows[: max(1, min(limit, 500))]


def resolve_proposal(
    proposal_id: str,
    status: str,
    note: str = "",
) -> Optional[dict[str, Any]]:
    status = (status or "").upper()
    if status not in (ProposalStatus.APPROVED.value, ProposalStatus.REJECTED.value, ProposalStatus.EXPIRED.value):
        raise ValueError("status must be APPROVED, REJECTED, or EXPIRED")
    rec = get_proposal(proposal_id)
    if not rec:
        return None
    rec = dict(rec)
    rec["status"] = status
    rec["resolution_note"] = note or ""
    rec["resolved_at"] = _utc_now_iso()
    with _lock:
        _by_id[proposal_id] = rec
        try:
            d = _data_dir()
            d.mkdir(parents=True, exist_ok=True)
            with open(_jsonl_path(), "a", encoding="utf-8") as f:
                f.write(json.dumps({"event": "resolve", **rec}, default=str) + "\n")
        except Exception as e:
            logger.warning("proposal resolve append failed: %s", e)
    return rec


_loaded = False


def _load_file_once() -> None:
    global _loaded
    if _loaded:
        return
    path = _jsonl_path()
    if not path.exists():
        _loaded = True
        return
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                pid = row.get("proposal_id")
                if not pid:
                    continue
                with _lock:
                    # later lines win (including resolve events)
                    _by_id[pid] = row
        _loaded = True
    except Exception as e:
        logger.warning("proposal file load failed: %s", e)
        _loaded = True


def clear_for_tests() -> None:
    global _loaded
    with _lock:
        _by_id.clear()
    _loaded = False


def notify_payload_for(proposal: ActionProposal | dict[str, Any]) -> dict[str, Any]:
    """Fields to include in manager notification message/data."""
    if isinstance(proposal, ActionProposal):
        d = proposal.to_dict()
    else:
        d = dict(proposal)
    return {
        "proposal_id": d.get("proposal_id"),
        "type": d.get("type"),
        "summary": d.get("summary"),
        "rationale": d.get("rationale"),
        "store_id": d.get("store_id"),
        "agent": d.get("agent"),
        "requires_approval": True,
        "status": d.get("status", "PENDING"),
    }
