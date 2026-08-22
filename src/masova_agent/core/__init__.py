"""Core agent module"""

__all__ = [
    "MaSoVaAgent",
    "get_agent",
    "send_message",
    "root_agent",
    "agent",
    "app",
]


def __getattr__(name: str):
    if name in ("root_agent", "agent", "app", "send_message_async", "send_message", "MaSoVaAgent", "get_agent"):
        from . import agent as _agent_module
        return getattr(_agent_module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
