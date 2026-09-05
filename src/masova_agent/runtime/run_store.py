"""
Durable run-record storage.

Primary: in-memory + append-only JSONL under data/runs/ (gitignored).
Production (Cloud Run): Firestore when DURABLE_STORE=firestore.
Mirrors runtime/proposal_store.py's pattern — same lock, same
lazy-load-once, same "later lines win" reconciliation for last-per-agent.

Feeds the Agent Registry's `last_run` field (see registry.py) and Phase 3
observability: full JSONL history (`list_runs` / `get_run_by_id`),
structured `reasoning_trace` on each persisted audit record, and a
SHA-256 hash chain for tamper-evidence.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Optional

from . import durable

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_by_agent: dict[str, dict[str, Any]] = {}
_all_records: list[dict[str, Any]] = []
_loaded = False
_last_hash: str = "genesis"


def _data_dir() -> Path:
    root = os.getenv("RUN_DATA_DIR")
    if root:
        return Path(root)
    return Path(__file__).resolve().parents[3] / "data" / "runs"


def _jsonl_path() -> Path:
    return _data_dir() / "runs.jsonl"


def _canonical_json(record: dict[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)


def _compute_hash(prev_hash: str, record: dict[str, Any]) -> str:
    payload = prev_hash + _canonical_json(record)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def record_run(record: dict[str, Any]) -> dict[str, Any]:
    global _last_hash
    agent = str(record.get("agent") or record.get("agent_name") or "")
    if not agent:
        raise ValueError("record_run requires a non-empty 'agent' key")
    rec = dict(record)
    rec["agent"] = agent
    _load_file_once()  # restore on-disk tip before extending the chain
    with _lock:
        prev_hash = _last_hash
        record_hash = _compute_hash(prev_hash, rec)
        rec["prev_hash"] = prev_hash
        rec["record_hash"] = record_hash
        rec["chain_seq"] = len([r for r in _all_records if r.get("record_hash")]) + 1
        _last_hash = record_hash
        _by_agent[agent] = rec
        _all_records.append(rec)
        doc_id = str(rec.get("run_id") or record_hash)
        if not durable.put_run(rec, doc_id=doc_id):
            try:
                d = _data_dir()
                d.mkdir(parents=True, exist_ok=True)
                with open(_jsonl_path(), "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, default=str) + "\n")
            except Exception as e:
                logger.warning("run record file append failed: %s", e)
    return rec


def list_runs(
    *,
    agent: Optional[str] = None,
    store_id: Optional[str] = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    _load_file_once()
    with _lock:
        rows = list(_all_records)
    if agent:
        rows = [r for r in rows if r.get("agent") == agent]
    if store_id:
        rows = [r for r in rows if r.get("store_id") == store_id]
    rows.sort(key=lambda r: r.get("at") or "", reverse=True)
    return rows[: max(1, min(limit, 500))]


def upsert_run(record: dict[str, Any]) -> dict[str, Any]:
    """Update or insert a run without advancing the hash chain.

    Used for in-flight ``status=="running"`` stubs and mid-run tool traces.
    Terminal audit lines still go through ``record_run``.
    """
    rec = dict(record)
    agent = str(rec.get("agent") or rec.get("agent_name") or "")
    if not agent:
        raise ValueError("upsert_run requires a non-empty 'agent' key")
    rec["agent"] = agent
    run_id = rec.get("run_id")
    _load_file_once()
    with _lock:
        replaced = False
        if run_id:
            for i, row in enumerate(_all_records):
                if row.get("run_id") == run_id and not row.get("record_hash"):
                    merged = dict(row)
                    merged.update(rec)
                    _all_records[i] = merged
                    rec = merged
                    replaced = True
                    break
        if not replaced:
            _all_records.append(rec)
        _by_agent[agent] = rec
        doc_id = str(rec.get("run_id") or rec.get("record_hash") or agent)
        durable.put_run(rec, doc_id=doc_id)
    return rec


def chain_report() -> dict[str, Any]:
    """Hash-chain status for consoles: verified, length, tip."""
    verified = verify_chain()
    _load_file_once()
    with _lock:
        chained = [r for r in _all_records if r.get("record_hash")]
        length = len(chained)
        tip = str(_last_hash or "genesis")
        if chained:
            tip = str(chained[-1].get("record_hash") or tip)
    return {"verified": verified, "length": length, "tip": tip}


def get_run_by_id(run_id: str) -> Optional[dict[str, Any]]:
    _load_file_once()
    with _lock:
        for row in reversed(_all_records):
            if row.get("run_id") == run_id:
                return dict(row)
    return None


def get_last_run(agent_name: str) -> Optional[dict[str, Any]]:
    """Catalog projection only — not the full audit record."""
    _load_file_once()
    with _lock:
        hit = _by_agent.get(agent_name)
        if not hit:
            return None
        return {
            "status": hit.get("status"),
            "used_fallback": bool(hit.get("used_fallback")),
            "at": hit.get("at"),
            "trigger_type": hit.get("trigger_type"),
        }


def verify_chain(agent_name: Optional[str] = None) -> bool:
    """Verify the whole-file hash chain. agent_name kept for API compat; unused."""
    del agent_name  # chain is global; filter would false-negative on interleaved rows
    _load_file_once()
    if durable.firestore_enabled():
        with _lock:
            chained = [r for r in _all_records if r.get("record_hash")]
        chained.sort(key=lambda r: int(r.get("chain_seq") or 0) or 0)
        prev = "genesis"
        for row in chained:
            claimed_prev = row.get("prev_hash", "")
            claimed_hash = row.get("record_hash", "")
            body = {
                k: v
                for k, v in row.items()
                if k not in ("prev_hash", "record_hash", "chain_seq", "_doc_id")
            }
            expected = _compute_hash(claimed_prev, body)
            if claimed_prev != prev or claimed_hash != expected:
                return False
            prev = claimed_hash
        return True
    path = _jsonl_path()
    if not path.exists():
        return True
    prev = "genesis"
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                claimed_prev = row.get("prev_hash", "")
                claimed_hash = row.get("record_hash", "")
                body = {
                    k: v
                    for k, v in row.items()
                    if k not in ("prev_hash", "record_hash", "chain_seq", "_doc_id")
                }
                expected = _compute_hash(claimed_prev, body)
                if claimed_prev != prev or claimed_hash != expected:
                    return False
                prev = claimed_hash
    except Exception as e:
        logger.warning("chain verification failed to read file: %s", e)
        return False
    return True


def _load_file_once() -> None:
    global _loaded, _last_hash
    if _loaded:
        return
    if durable.firestore_enabled():
        rows = durable.list_runs()
        if rows or durable.get_client() is not None:
            rows.sort(
                key=lambda r: (
                    int(r.get("chain_seq") or 0),
                    str(r.get("at") or ""),
                )
            )
            tip = "genesis"
            with _lock:
                _all_records.clear()
                _by_agent.clear()
                for row in rows:
                    agent = row.get("agent")
                    if not agent:
                        continue
                    _by_agent[str(agent)] = row
                    _all_records.append(row)
                    rh = row.get("record_hash")
                    if isinstance(rh, str) and rh:
                        tip = rh
                _last_hash = tip
            _loaded = True
            logger.info("Loaded %s run records from Firestore", len(_all_records))
            return
    path = _jsonl_path()
    if not path.exists():
        _loaded = True
        return
    tip = "genesis"
    try:
        with open(path, encoding="utf-8") as f:
            with _lock:
                _all_records.clear()
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                agent = row.get("agent")
                if not agent:
                    continue
                with _lock:
                    _by_agent[agent] = row  # later lines win
                    _all_records.append(row)
                rh = row.get("record_hash")
                if isinstance(rh, str) and rh:
                    tip = rh
        with _lock:
            _last_hash = tip
        _loaded = True
    except Exception as e:
        logger.warning("run record file load failed: %s", e)
        _loaded = True


def clear_for_tests() -> None:
    global _loaded, _last_hash
    with _lock:
        _by_agent.clear()
        _all_records.clear()
    _loaded = False
    _last_hash = "genesis"
    durable.reset_client_for_tests()


STALE_CHAIN_WARNING = (
    "stale run log; delete data/runs and re-trigger for a clean chain"
)


def warn_stale_demo_run_log() -> bool:
    """DEMO_MODE start hook. Returns True if the chain is intact.

    Never rewrites history. A broken chain stays broken until an operator
    (or reset_run_log_for_demo) deletes the JSONL.
    """
    from ..services.demo_backend import demo_mode

    if not demo_mode():
        return verify_chain()
    path = _jsonl_path()
    if not path.exists():
        return True
    ok = verify_chain()
    if not ok:
        logger.warning(STALE_CHAIN_WARNING)
    return ok


def reset_run_log_for_demo() -> None:
    """Wipe the JSONL + in-memory store so a new hash chain can start.

    Documented helper for tests and a local demo reset after the stale-chain
    warning. Not invoked on process start — never silently rewrite history.
    """
    from ..services.demo_backend import demo_mode

    if not demo_mode() and not os.getenv("RUN_DATA_DIR"):
        logger.warning(
            "reset_run_log_for_demo refused: DEMO_MODE/RUN_DATA_DIR not set"
        )
        return
    path = _jsonl_path()
    try:
        if path.exists():
            path.unlink()
    except Exception as e:
        logger.warning("reset_run_log_for_demo could not delete %s: %s", path, e)
    clear_for_tests()
