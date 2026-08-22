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


def _data_dir() -> Path:
    root = os.getenv("RUN_DATA_DIR")
    if root:
        return Path(root)
    return Path(__file__).resolve().parents[3] / "data" / "runs"


def _jsonl_path() -> Path:
    return _data_dir() / "runs.jsonl"


def record_run(record: dict[str, Any]) -> dict[str, Any]:
    agent = str(record.get("agent") or record.get("agent_name") or "")
    if not agent:
        raise ValueError("record_run requires a non-empty 'agent' key")
    rec = dict(record)
    rec["agent"] = agent
    with _lock:
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
    global _loaded
    with _lock:
        _by_agent.clear()
    _loaded = False
