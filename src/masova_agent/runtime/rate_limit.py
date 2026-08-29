"""Per-key token bucket. In-process; fail open if Redis is down."""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict, deque
from typing import Deque

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_hits: dict[str, Deque[float]] = defaultdict(deque)


def _budget() -> int:
    try:
        return max(1, int(os.getenv("RATE_LIMIT_PER_MIN", "60")))
    except ValueError:
        return 60


def reset_for_tests() -> None:
    with _lock:
        _hits.clear()


def check_rate_limit_sync(key: str) -> bool:
    """True if the request is allowed. Fail open on unexpected errors."""
    try:
        now = time.time()
        window = 60.0
        budget = _budget()
        with _lock:
            q = _hits[key]
            while q and now - q[0] >= window:
                q.popleft()
            if len(q) >= budget:
                return False
            q.append(now)
            return True
    except Exception as e:
        logger.warning("rate limit failed open: %s", e)
        return True


async def check_rate_limit(key: str) -> bool:
    return check_rate_limit_sync(key)
