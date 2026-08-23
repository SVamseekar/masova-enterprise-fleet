"""
Durable last-run-per-agent storage (v1).

Primary: in-memory + append-only JSONL under data/runs/ (gitignored).
Mirrors runtime/proposal_store.py's pattern exactly — same lock, same
lazy-load-once, same "later lines win" reconciliation.

Feeds the Agent Registry's `last_run` field (see registry.py) and is the
foundation Phase 3 (reasoning-chain observability) extends with a
structured per-tool-call trace and hash chain — this module only tracks
the most recent record per agent, nothing more.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_by_agent: dict[str, dict[str, Any]] = {}
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
    with _lock:
        prev_hash = _last_hash
        record_hash = _compute_hash(prev_hash, rec)
        rec["prev_hash"] = prev_hash
        rec["record_hash"] = record_hash
        _last_hash = record_hash
        _by_agent[agent] = rec
        try:
            d = _data_dir()
            d.mkdir(parents=True, exist_ok=True)
            with open(_jsonl_path(), "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, default=str) + "\n")
        except Exception as e:
            logger.warning("run record file append failed: %s", e)
    return rec


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
                if agent_name and row.get("agent") != agent_name:
                    continue
                claimed_prev = row.get("prev_hash", "")
                claimed_hash = row.get("record_hash", "")
                body = {k: v for k, v in row.items() if k not in ("prev_hash", "record_hash")}
                expected = _compute_hash(claimed_prev, body)
                if claimed_prev != prev or claimed_hash != expected:
                    return False
                prev = claimed_hash
    except Exception as e:
        logger.warning("chain verification failed to read file: %s", e)
        return False
    return True


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
                agent = row.get("agent")
                if not agent:
                    continue
                with _lock:
                    _by_agent[agent] = row  # later lines win
        _loaded = True
    except Exception as e:
        logger.warning("run record file load failed: %s", e)
        _loaded = True


def clear_for_tests() -> None:
    global _loaded, _last_hash
    with _lock:
        _by_agent.clear()
    _loaded = False
    _last_hash = "genesis"
