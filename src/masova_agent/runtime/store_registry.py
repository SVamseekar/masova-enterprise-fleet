"""
Canonical store_id resolution — the one place that decides whether a
store_id a client sent is real.

Backed by GET /api/stores (real backend, or demo SQLite in DEMO_MODE) via a
short-TTL in-process cache, so validating every trigger/chat request doesn't
mean a fresh backend call each time. Accepts either a store's real id or its
short code (matches list_stores' shape); rejects everything else, including
empty string, so a mistyped or garbage store_id never reaches proposal/run
creation.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_cache_ids: set[str] = set()
_cache_at: float = 0.0
_CACHE_TTL_SEC = 30.0


async def _fetch_store_ids() -> tuple[set[str], bool]:
    """Returns (ids, ok). ok=False means the catalog couldn't be fetched at all —
    caller must fail open (allow) rather than treat every id as unknown."""
    from ..tools.ops_tools import list_stores

    try:
        res = await list_stores()
    except Exception as e:
        logger.warning("store_registry: list_stores raised, failing open: %s", e)
        return set(_cache_ids), False
    if not isinstance(res, dict) or not res.get("ok"):
        logger.warning("store_registry: list_stores failed, keeping stale cache")
        return set(_cache_ids), bool(_cache_ids)  # stale-but-nonempty still usable
    ids: set[str] = set()
    for s in res.get("stores") or []:
        sid = s.get("id")
        if sid:
            ids.add(str(sid))
    return ids, True


async def known_store_ids(force_refresh: bool = False) -> tuple[set[str], bool]:
    """Returns (ids, ok) — see is_known_store for how ok=False should be handled."""
    global _cache_at
    now = time.time()
    with _lock:
        stale = force_refresh or (now - _cache_at) > _CACHE_TTL_SEC
    if not stale:
        with _lock:
            return set(_cache_ids), True

    fresh, ok = await _fetch_store_ids()
    with _lock:
        if fresh:
            _cache_ids.clear()
            _cache_ids.update(fresh)
        _cache_at = now
        return set(_cache_ids), ok


async def is_known_store(store_id: Optional[str]) -> bool:
    """
    True if store_id is a confirmed real store. Fails OPEN (returns True) when
    the store catalog itself couldn't be determined — e.g. backend unreachable,
    demo DB not configured in this process — so infrastructure trouble never
    blocks a request that would otherwise have been valid. Only returns False
    when the catalog was actually fetched and the id genuinely isn't in it.
    """
    sid = (store_id or "").strip()
    if not sid:
        return False
    ids, ok = await known_store_ids()
    if not ok:
        return True
    return sid in ids


def clear_for_tests() -> None:
    global _cache_at
    with _lock:
        _cache_ids.clear()
        _cache_at = 0.0
