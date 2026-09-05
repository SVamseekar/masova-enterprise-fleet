"""Optional Firestore backend for proposals and run records.

Local tests and laptops keep using JSONL (DURABLE_STORE unset).
Cloud Run sets DURABLE_STORE=firestore so HITL OK counts survive deploys.

Documents store indexed fields plus a JSON `record` blob so nested payloads
stay valid Firestore values. Fail-open: if Firestore is unreachable, callers
keep the in-process JSONL path.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

PROPOSALS = "fleet_proposals"
RUNS = "fleet_runs"

_client = None
_client_failed = False


def firestore_enabled() -> bool:
    return os.getenv("DURABLE_STORE", "").strip().lower() in ("firestore", "fs")


def _project() -> str:
    return (
        os.getenv("FIRESTORE_PROJECT")
        or os.getenv("GOOGLE_CLOUD_PROJECT")
        or os.getenv("GCLOUD_PROJECT")
        or ""
    ).strip()


def get_client():
    """Lazy Firestore client. None when disabled or import/auth fails."""
    global _client, _client_failed
    if not firestore_enabled() or _client_failed:
        return None
    if _client is not None:
        return _client
    try:
        from google.cloud import firestore  # type: ignore

        project = _project() or None
        _client = firestore.Client(project=project) if project else firestore.Client()
        return _client
    except Exception as e:
        _client_failed = True
        logger.warning("Firestore client unavailable (%s) — using JSONL", e)
        return None


def reset_client_for_tests() -> None:
    global _client, _client_failed
    _client = None
    _client_failed = False


def _pack(rec: dict[str, Any], extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    doc = {
        "proposal_id": str(rec.get("proposal_id") or ""),
        "run_id": str(rec.get("run_id") or ""),
        "store_id": str(rec.get("store_id") or ""),
        "status": str(rec.get("status") or ""),
        "agent": str(rec.get("agent") or rec.get("agent_name") or ""),
        "type": str(rec.get("type") or ""),
        "created_at": str(rec.get("created_at") or rec.get("at") or ""),
        "record": json.dumps(rec, default=str),
    }
    if extra:
        doc.update(extra)
    return doc


def _unpack(doc: dict[str, Any]) -> Optional[dict[str, Any]]:
    raw = doc.get("record")
    if isinstance(raw, str) and raw:
        try:
            rec = json.loads(raw)
            if isinstance(rec, dict):
                return rec
        except json.JSONDecodeError:
            return None
    return None


def put_proposal(rec: dict[str, Any]) -> bool:
    client = get_client()
    pid = str(rec.get("proposal_id") or "")
    if client is None or not pid:
        return False
    try:
        client.collection(PROPOSALS).document(pid).set(_pack(rec))
        return True
    except Exception as e:
        logger.warning("Firestore put_proposal failed: %s", e)
        return False


def get_proposal(proposal_id: str) -> Optional[dict[str, Any]]:
    client = get_client()
    if client is None or not proposal_id:
        return None
    try:
        snap = client.collection(PROPOSALS).document(proposal_id).get()
        if not snap.exists:
            return None
        return _unpack(snap.to_dict() or {})
    except Exception as e:
        logger.warning("Firestore get_proposal failed: %s", e)
        return None


def list_proposals() -> list[dict[str, Any]]:
    client = get_client()
    if client is None:
        return []
    rows: list[dict[str, Any]] = []
    try:
        for snap in client.collection(PROPOSALS).stream():
            rec = _unpack(snap.to_dict() or {})
            if rec and rec.get("proposal_id"):
                rows.append(rec)
    except Exception as e:
        logger.warning("Firestore list_proposals failed: %s", e)
    return rows


def put_run(rec: dict[str, Any], *, doc_id: str) -> bool:
    client = get_client()
    if client is None or not doc_id:
        return False
    try:
        extra = {
            "chain_seq": rec.get("chain_seq"),
            "record_hash": rec.get("record_hash") or "",
        }
        client.collection(RUNS).document(str(doc_id)).set(_pack(rec, extra))
        return True
    except Exception as e:
        logger.warning("Firestore put_run failed: %s", e)
        return False


def list_runs() -> list[dict[str, Any]]:
    client = get_client()
    if client is None:
        return []
    rows: list[dict[str, Any]] = []
    try:
        for snap in client.collection(RUNS).stream():
            rec = _unpack(snap.to_dict() or {})
            if rec:
                rec["_doc_id"] = snap.id
                rows.append(rec)
    except Exception as e:
        logger.warning("Firestore list_runs failed: %s", e)
    return rows
