"""
Authentication for the MaSoVa support agent's HTTP surface.

Two distinct trust boundaries:

1. Customer-facing endpoints (/agent/chat) — the caller must present the
   same JWT issued by the MaSoVa backend (core-service) for that customer.
   We verify it locally (HS512, same JWT_SECRET as the backend) so no
   network round-trip is needed, and so identity used for downstream tool
   calls is cryptographically real rather than parsed from chat text.

2. Internal/ops endpoints (/agents/{name}/trigger) — called by schedulers,
   managers, or internal tooling, not customers. These are gated by a
   static service-to-service API key (AGENT_TRIGGER_API_KEY), not a
   customer JWT, since there's no per-customer identity to bind to.
"""

import contextvars
import logging
import os
from dataclasses import dataclass
from typing import Optional

import jwt
from fastapi import Header, HTTPException, status

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentIdentity:
    """Authenticated identity for the current request, bound from a verified JWT."""
    user_id: str
    user_type: str
    store_id: Optional[str]
    raw_token: str


# Per-request authenticated identity. Set once at the endpoint boundary after
# JWT verification; read by tool functions and _headers() so they bind to the
# verified identity instead of trusting LLM-parsed arguments or a hardcoded role.
_current_identity: "contextvars.ContextVar[Optional[AgentIdentity]]" = contextvars.ContextVar(
    "masova_agent_identity", default=None
)


def get_current_identity() -> AgentIdentity:
    identity = _current_identity.get()
    if identity is None:
        # Tool functions must never run without a bound identity — fail closed.
        raise RuntimeError(
            "No authenticated identity bound to this request. "
            "Tool functions must only run inside a request authenticated via verify_customer_jwt."
        )
    return identity


def bind_identity(identity: AgentIdentity) -> contextvars.Token:
    return _current_identity.set(identity)


def reset_identity(token: contextvars.Token) -> None:
    _current_identity.reset(token)


def _jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET", "")
    if not secret:
        raise RuntimeError(
            "JWT_SECRET is not configured. The agent cannot verify customer identity "
            "without the same secret used by the MaSoVa backend."
        )
    return secret


async def verify_customer_jwt(authorization: str = Header(default="")) -> AgentIdentity:
    """
    FastAPI dependency for customer-facing endpoints.

    Verifies the bearer token using the same HS512 secret as the backend's
    JwtAuthenticationFilter, then returns the real, cryptographically-attested
    identity. Raises 401 on any failure — never falls back to trusting
    request-body fields.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or malformed Authorization header")

    token = authorization[len("Bearer "):].strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    try:
        claims = jwt.decode(token, _jwt_secret(), algorithms=["HS512"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError as e:
        logger.warning("JWT verification failed: %s", e)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing subject claim")

    return AgentIdentity(
        user_id=user_id,
        user_type=claims.get("userType", "CUSTOMER"),
        store_id=claims.get("storeId"),
        raw_token=token,
    )


async def verify_trigger_api_key(x_agent_api_key: str = Header(default="")) -> None:
    """
    FastAPI dependency for internal /agents/{name}/trigger endpoints.

    These are scheduler/ops-triggered, not tied to a single customer, so they
    are gated by a static service API key rather than a customer JWT.
    """
    expected = os.getenv("AGENT_TRIGGER_API_KEY", "")
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent trigger endpoints are not configured (AGENT_TRIGGER_API_KEY unset)",
        )
    if not x_agent_api_key or x_agent_api_key != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing API key")
