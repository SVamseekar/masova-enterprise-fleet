"""
Lightweight metrics hooks (v1 = structured counters + log lines).

No external metrics backend required for CI. Ops can scrape logs for:
  masova_metric runs_total|fallback_total|proposals_total|llm_error_total
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from typing import Any

logger = logging.getLogger("masova_agent.metrics")

_lock = threading.Lock()
# agent -> counter_name -> int
_counters: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))


def incr(agent: str, name: str, n: int = 1) -> None:
    agent = agent or "_unknown"
    with _lock:
        _counters[agent][name] += n
        value = _counters[agent][name]
    logger.info(
        "masova_metric agent=%s name=%s value=%s delta=%s",
        agent,
        name,
        value,
        n,
    )


def snapshot() -> dict[str, dict[str, int]]:
    with _lock:
        return {a: dict(c) for a, c in _counters.items()}


def reset_for_tests() -> None:
    with _lock:
        _counters.clear()


def record_run(
    *,
    agent: str,
    used_fallback: bool,
    proposal_count: int,
    llm_error: bool = False,
    status: str = "ok",
) -> None:
    incr(agent, "runs_total")
    if used_fallback:
        incr(agent, "fallback_total")
    if proposal_count:
        incr(agent, "proposals_total", proposal_count)
    if llm_error:
        incr(agent, "llm_error_total")
    if status == "error":
        incr(agent, "error_total")
