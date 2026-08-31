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
from .ops_contract import SIDE_EFFECT_TYPES, SNAPSHOT_AGENTS

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
        # Preserve non-canonical keys used by consoles (e.g. run_id)
        if isinstance(proposal, dict) and proposal.get("run_id"):
            rec["run_id"] = proposal["run_id"]
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


def is_side_effect(rec: dict[str, Any] | None) -> bool:
    return str((rec or {}).get("type") or "") in SIDE_EFFECT_TYPES


def _run_id_of(rec: dict[str, Any]) -> str:
    if rec.get("run_id"):
        return str(rec["run_id"])
    payload = rec.get("payload") or {}
    return str(payload.get("run_id") or "")


def _review_id_of(rec: dict[str, Any]) -> str:
    payload = rec.get("payload") or {}
    return str(payload.get("review_id") or payload.get("reviewId") or "")


def _filtered_rows(
    *,
    store_id: Optional[str] = None,
    status: Optional[str] = None,
    agent: Optional[str] = None,
    type: Optional[str] = None,
    exclude_side_effects: bool = False,
) -> list[dict[str, Any]]:
    _load_file_once()
    with _lock:
        rows = [dict(r) for r in _by_id.values()]
    if store_id:
        rows = [r for r in rows if r.get("store_id") == store_id]
    if status:
        rows = [r for r in rows if str(r.get("status")) == status]
    if agent:
        rows = [r for r in rows if r.get("agent") == agent]
    if type:
        rows = [r for r in rows if r.get("type") == type]
    if exclude_side_effects:
        rows = [r for r in rows if not is_side_effect(r)]
    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return rows


def latest_open(
    store_id: str,
    *,
    type: Optional[str] = None,
    agent: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    rows = list_proposals(
        store_id=store_id,
        status=ProposalStatus.PENDING.value,
        type=type,
        agent=agent,
        limit=1,
        exclude_side_effects=True,
    )
    return dict(rows[0]) if rows else None


def list_proposals(
    *,
    store_id: Optional[str] = None,
    status: Optional[str] = None,
    agent: Optional[str] = None,
    type: Optional[str] = None,
    limit: int = 100,
    exclude_side_effects: bool = False,
) -> list[dict[str, Any]]:
    rows = _filtered_rows(
        store_id=store_id,
        status=status,
        agent=agent,
        type=type,
        exclude_side_effects=exclude_side_effects,
    )
    if limit is None or int(limit) <= 0:
        return rows
    return rows[: min(int(limit), 10_000)]


def count_proposals(
    *,
    store_id: Optional[str] = None,
    status: Optional[str] = None,
    agent: Optional[str] = None,
    type: Optional[str] = None,
    exclude_side_effects: bool = False,
) -> int:
    """True matching count, unbounded by the list-response page cap."""
    return len(
        _filtered_rows(
            store_id=store_id,
            status=status,
            agent=agent,
            type=type,
            exclude_side_effects=exclude_side_effects,
        )
    )


def resolve_proposal(
    proposal_id: str,
    status: str,
    note: str = "",
) -> Optional[dict[str, Any]]:
    status = (status or "").upper()
    if status not in (
        ProposalStatus.APPROVED.value,
        ProposalStatus.REJECTED.value,
        ProposalStatus.EXPIRED.value,
        ProposalStatus.SUPERSEDED.value,
    ):
        raise ValueError("status must be APPROVED, REJECTED, EXPIRED, or SUPERSEDED")
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


def _open_group_key(rec: dict[str, Any]) -> tuple[str, str, str]:
    """Group that a newer run is allowed to replace."""
    store_id = str(rec.get("store_id") or "")
    agent = str(rec.get("agent") or "")
    if agent == "review_response":
        return (store_id, agent, _review_id_of(rec) or str(rec.get("proposal_id") or ""))
    return (store_id, agent, "")


def supersede_stale_pending(
    *,
    store_id: str,
    agent: str,
    keep_ids: Optional[set[str]] = None,
    keep_run_id: Optional[str] = None,
    review_id: str = "",
    note: str = "",
) -> int:
    """
    Close leftover PENDING cards for this store + agent.

    Snapshot agents (inventory, demand, shifts, …): every older run is replaced.
    Review drafts: only the same review_id is replaced.
    """
    keep_ids = {str(x) for x in (keep_ids or set()) if x}
    keep_run_id = str(keep_run_id or "")
    pending = _filtered_rows(store_id=store_id, status="PENDING", agent=agent)
    expired = 0
    reason = note or (
        f"Superseded by run {keep_run_id}" if keep_run_id else "Superseded by a newer agent run"
    )
    for rec in pending:
        pid = str(rec.get("proposal_id") or "")
        if not pid or pid in keep_ids:
            continue
        if keep_run_id and _run_id_of(rec) == keep_run_id:
            continue
        if agent == "review_response":
            rid = _review_id_of(rec)
            if review_id:
                if rid != str(review_id):
                    continue
            elif rid:
                # Don't wipe unrelated reviews when the new draft has no id.
                continue
        elif agent not in SNAPSHOT_AGENTS and agent != "review_response":
            continue
        try:
            resolve_proposal(pid, ProposalStatus.SUPERSEDED.value, note=reason)
            expired += 1
        except Exception as e:
            logger.warning("supersede failed for %s: %s", pid, e)
    return expired


def sweep_stale_open_queue() -> dict[str, int]:
    """
    Fleet-wide cleanup so rail counts match current decisions.

    - Side-effect NOTIFY_MANAGERS cards are never HITL — close them.
    - For each (store, agent) snapshot group, keep only the latest run.
    - For review drafts, keep only the latest card per review_id.
    """
    pending = _filtered_rows(status="PENDING", exclude_side_effects=False)
    closed_notify = 0
    closed_stale = 0
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for rec in pending:
        if is_side_effect(rec):
            pid = rec.get("proposal_id")
            if not pid:
                continue
            try:
                resolve_proposal(
                    str(pid),
                    ProposalStatus.SUPERSEDED.value,
                    note="Notification is not a manager decision card",
                )
                closed_notify += 1
            except Exception as e:
                logger.warning("notify supersede failed for %s: %s", pid, e)
            continue
        groups.setdefault(_open_group_key(rec), []).append(rec)

    for _key, recs in groups.items():
        recs.sort(key=lambda r: r.get("created_at") or "", reverse=True)
        latest_run = _run_id_of(recs[0])
        keep_ids: set[str] = set()
        if latest_run:
            keep_ids = {
                str(r.get("proposal_id"))
                for r in recs
                if _run_id_of(r) == latest_run and r.get("proposal_id")
            }
        elif recs[0].get("proposal_id"):
            keep_ids = {str(recs[0]["proposal_id"])}
        for rec in recs:
            pid = rec.get("proposal_id")
            if not pid or str(pid) in keep_ids:
                continue
            try:
                resolve_proposal(
                    str(pid),
                    ProposalStatus.SUPERSEDED.value,
                    note="Superseded by a newer agent run for this store",
                )
                closed_stale += 1
            except Exception as e:
                logger.warning("stale sweep failed for %s: %s", pid, e)

    if closed_notify or closed_stale:
        logger.info(
            "Open-queue sweep: closed %s notify cards, %s superseded drafts",
            closed_notify,
            closed_stale,
        )
    return {"notify": closed_notify, "stale": closed_stale}


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
