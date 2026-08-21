"""
MaSoVa Customer Support Agent

A professional AI agent built with Google ADK for customer support operations.
"""
__version__ = "0.1.0"

# Core ADK imports are lazy to avoid pulling in google.adk at import time
# (which fails in environments without the package, e.g. test runners).
# Import directly from submodules when you need them:
#   from masova_agent.core import MaSoVaAgent, get_agent
#   from masova_agent.agent import send_message_async

from .utils import get_config, get_logger, setup_logging
from .exceptions import (
    MaSoVaException,
    CustomerNotFoundError,
    OrderNotFoundError,
    LocationServiceError,
    ConfigurationError,
    AgentError,
)

__all__ = [
    # Utilities
    "get_config",
    "get_logger",
    "setup_logging",
    # Exceptions
    "MaSoVaException",
    "CustomerNotFoundError",
    "OrderNotFoundError",
    "LocationServiceError",
    "ConfigurationError",
    "AgentError",
    # Version
    "__version__",
]
