"""
Idempotency for ops propose paths.

Business key: agent + store_id + action + time window (date or hour bucket).
In-process memory by default; optional Redis if REDIS_URL is set and reachable.
Never blocks ops on Redis failure — falls open to allow the draft.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# In-process: key -> (expires_at_epoch, payload)
_store: dict[str, tuple[float, dict[str, Any]]] = {}
_lock = threading.Lock()
_DEFAULT_TTL_SEC = 6 * 3600  # 6h aligns with inventory cron


def hour_bucket(dt: Optional[datetime] = None) -> str:
    dt = dt or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y%m%d%H")


def date_bucket(dt: Optional[datetime] = None) -> str:
    dt = dt or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y%m%d")


def make_key(
    agent: str,
    store_id: str,
    action: str,
    *,
    window: str = "hour",
    extra: str = "",
    dt: Optional[datetime] = None,
) -> str:
    """
    Build idempotency key.

    window: 'hour' | 'date' | free-form string already bucketed
    """
    if window == "hour":
        bucket = hour_bucket(dt)
    elif window == "date":
        bucket = date_bucket(dt)
    else:
        bucket = window
    parts = ["idem", agent, store_id or "_", action, bucket]
    if extra:
        parts.append(str(extra))
    return ":".join(parts)


def _purge_expired(now: float) -> None:
    dead = [k for k, (exp, _) in _store.items() if exp <= now]
    for k in dead:
        del _store[k]


def seen(key: str) -> Optional[dict[str, Any]]:
    """Return prior payload if key already claimed and not expired."""
    now = time.time()
    with _lock:
        _purge_expired(now)
        hit = _store.get(key)
        if not hit:
            return None
        exp, payload = hit
        if exp <= now:
            del _store[key]
            return None
        return dict(payload)


def claim(
    key: str,
    payload: Optional[dict[str, Any]] = None,
    *,
    ttl_sec: int = _DEFAULT_TTL_SEC,
) -> tuple[bool, dict[str, Any]]:
    """
    Try to claim key. Returns (is_new, payload).

    is_new=False means duplicate within TTL — caller should skip create.
    """
    now = time.time()
    payload = dict(payload or {})
    payload.setdefault("claimed_at", datetime.now(timezone.utc).isoformat())
    with _lock:
        _purge_expired(now)
        hit = _store.get(key)
        if hit and hit[0] > now:
            return False, dict(hit[1])
        _store[key] = (now + max(1, ttl_sec), payload)
    # Best-effort Redis mirror (non-blocking for correctness)
    _redis_set(key, payload, ttl_sec)
    return True, payload


def check_or_claim(
    key: str,
    payload: Optional[dict[str, Any]] = None,
    *,
    ttl_sec: int = _DEFAULT_TTL_SEC,
) -> tuple[bool, dict[str, Any]]:
    """Alias for claim — first call wins."""
    return claim(key, payload, ttl_sec=ttl_sec)


def clear_for_tests() -> None:
    with _lock:
        _store.clear()


def _redis_set(key: str, payload: dict[str, Any], ttl_sec: int) -> None:
    url = os.getenv("REDIS_URL") or os.getenv("REDIS_HOST")
    if not url:
        return
    try:
        import json
        import redis  # type: ignore

        host = os.getenv("REDIS_HOST", "127.0.0.1")
        port = int(os.getenv("REDIS_PORT", "6379"))
        db = int(os.getenv("REDIS_IDEMPOTENCY_DB", "2"))
        r = redis.Redis(host=host, port=port, db=db, socket_connect_timeout=0.3)
        r.setex(f"masova:idem:{key}", ttl_sec, json.dumps(payload, default=str))
    except Exception as e:
        logger.debug("idempotency redis set skipped: %s", e)
