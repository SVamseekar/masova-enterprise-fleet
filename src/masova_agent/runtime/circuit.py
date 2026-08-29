"""LLM circuit breaker: three consecutive failures skip the LLM path."""

from __future__ import annotations

import threading

_lock = threading.Lock()
_failures: dict[str, int] = {}
_OPEN_AFTER = 3


def reset_for_tests() -> None:
    with _lock:
        _failures.clear()


def record_failure(agent: str) -> None:
    with _lock:
        _failures[agent] = _failures.get(agent, 0) + 1


def record_success(agent: str) -> None:
    with _lock:
        _failures[agent] = 0


def allow_llm(agent: str) -> bool:
    with _lock:
        return _failures.get(agent, 0) < _OPEN_AFTER
