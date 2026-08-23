"""
Compatibility shim — single chat entry is `masova_agent.agent`.

Historical `MaSoVaAgent` class lived here; new code should import from
`masova_agent.agent` (root_agent, send_message_async).
"""

from __future__ import annotations

from typing import Optional

__all__ = [
    "root_agent",
    "agent",
    "app",
    "send_message_async",
    "send_message",
    "MaSoVaAgent",
    "get_agent",
]

_agent_instance: Optional["MaSoVaAgent"] = None


class MaSoVaAgent:
    """Deprecated thin wrapper around the module-level ADK agent."""

    def __init__(self):
        from .. import agent as _a
        self.llm_agent = _a.root_agent

    async def send_message_async(
        self,
        message: str,
        user_id: str = "anonymous",
        session_id: str = "default",
    ):
        from .. import agent as _a
        reply, _sid = await _a.send_message_async(message, user_id, session_id)
        return reply


def get_agent() -> MaSoVaAgent:
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = MaSoVaAgent()
    return _agent_instance


def __getattr__(name: str):
    if name in ("root_agent", "agent", "app", "send_message_async", "send_message"):
        from .. import agent as _a
        return getattr(_a, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

