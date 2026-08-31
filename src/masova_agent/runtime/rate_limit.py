"""
Enterprise-grade multi-tier token bucket rate limiter. In-process; fail open
if the check itself errors (never blocks traffic due to a limiter bug).

Features:
- Tiered budgets: AI inference vs high-frequency polling reads vs default routes.
- Key partitioning: prioritizes API key / Bearer token over client IP to isolate users.
- Production RFC headers: X-RateLimit-Limit, Remaining, Reset, Retry-After (via check_rate_limit_result).
- Demo & test headroom scaling: multiplies capacity in DEMO_MODE to prevent UI hiccups.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_hits: dict[str, Deque[float]] = defaultdict(deque)

TIER_AI = "ai"
TIER_READ = "read"
TIER_DEFAULT = "default"
TIER_EXEMPT = "exempt"

WINDOW_SECONDS = 60.0


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    reset_seconds: int
    retry_after: int = 0


def is_rate_limiting_disabled() -> bool:
    return os.getenv("RATE_LIMIT_DISABLED", "false").lower() in ("true", "1", "yes")


def is_demo_mode() -> bool:
    return os.getenv("DEMO_MODE", "false").lower() in ("true", "1", "yes")


def get_tier_budget(tier: str = TIER_DEFAULT) -> int:
    """Return requests-per-minute budget for the requested tier."""
    demo_multiplier = 5 if is_demo_mode() else 1

    try:
        if tier == TIER_AI:
            base = int(os.getenv("RATE_LIMIT_AI_PER_MIN", "180"))
        elif tier == TIER_READ:
            base = int(os.getenv("RATE_LIMIT_READ_PER_MIN", "1200"))
        else:
            base = int(os.getenv("RATE_LIMIT_PER_MIN", "60"))
    except (TypeError, ValueError):
        base = 60

    return max(1, base * demo_multiplier)


def classify_route_tier(path: str, method: str = "GET") -> str:
    """Classify an HTTP request path into its rate limit tier."""
    p = (path or "").rstrip("/")
    if not p:
        p = "/"

    # Exempt endpoints
    if (
        p in ("/health", "/metrics", "/favicon.ico", "/docs", "/redoc", "/openapi.json")
        or p.startswith("/console")
        or p.startswith("/static")
    ):
        return TIER_EXEMPT

    # AI / LLM inference & Specialist Agent execution
    if (
        p in ("/chat", "/agent/manager/chat")
        or "/trigger" in p
        or (p.startswith("/agents/") and method.upper() == "POST")
    ):
        return TIER_AI

    # High-frequency polling reads, demo table inspector, telemetry queries
    if (
        p in ("/agents", "/agent/runs", "/agent/proposals")
        or p.startswith("/agent/demo/")
        or p.startswith("/api/")
        or method.upper() == "GET"
    ):
        return TIER_READ

    return TIER_DEFAULT


def resolve_client_key(
    client_ip: Optional[str] = None,
    auth_header: Optional[str] = None,
    api_key_header: Optional[str] = None,
) -> str:
    """Derive client identity key: prefers auth token > client IP > anon."""
    if api_key_header and api_key_header.strip():
        return f"key:{api_key_header.strip()[:16]}"
    if auth_header and auth_header.strip():
        tok = auth_header.strip().replace("Bearer ", "").strip()
        if tok:
            return f"tok:{tok[:16]}"
    if client_ip and client_ip.strip():
        return f"ip:{client_ip.strip()}"
    return "anon"


def reset_for_tests() -> None:
    with _lock:
        _hits.clear()


def check_rate_limit_result(key: str, tier: str = TIER_DEFAULT) -> RateLimitResult:
    """Evaluate rate limit, returning detailed metrics for response headers."""
    if is_rate_limiting_disabled() or tier == TIER_EXEMPT:
        return RateLimitResult(allowed=True, limit=10000, remaining=10000, reset_seconds=0)

    try:
        now = time.time()
        budget = get_tier_budget(tier)
        scoped_key = f"{key}:{tier}" if tier != TIER_DEFAULT else key

        with _lock:
            q = _hits[scoped_key]
            while q and now - q[0] >= WINDOW_SECONDS:
                q.popleft()

            if len(q) >= budget:
                oldest = q[0]
                retry_after = max(1, int(WINDOW_SECONDS - (now - oldest)))
                return RateLimitResult(
                    allowed=False,
                    limit=budget,
                    remaining=0,
                    reset_seconds=retry_after,
                    retry_after=retry_after,
                )

            q.append(now)
            remaining = max(0, budget - len(q))
            reset_secs = max(1, int(WINDOW_SECONDS - (now - q[0]))) if q else int(WINDOW_SECONDS)
            return RateLimitResult(
                allowed=True,
                limit=budget,
                remaining=remaining,
                reset_seconds=reset_secs,
            )
    except Exception as e:
        logger.warning("rate limit check failed open: %s", e)
        return RateLimitResult(allowed=True, limit=600, remaining=600, reset_seconds=0)


def check_rate_limit_sync(key: str, tier: str = TIER_DEFAULT) -> bool:
    """Simple boolean check for backwards compatibility."""
    return check_rate_limit_result(key, tier=tier).allowed


async def check_rate_limit(key: str, tier: str = TIER_DEFAULT) -> bool:
    return check_rate_limit_sync(key, tier=tier)
