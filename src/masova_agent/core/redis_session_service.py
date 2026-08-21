"""
Redis-backed session service for MaSoVa Agent.
Replaces InMemorySessionService to persist conversation across restarts.
Falls back to InMemorySessionService if Redis is unavailable.
"""
import json
import uuid
import logging
from typing import Optional
from dataclasses import dataclass, field

import redis
from google.adk.sessions import InMemorySessionService

logger = logging.getLogger(__name__)

SESSION_TTL_SECONDS = 3600  # 1 hour
MAX_HISTORY_TURNS = 10


@dataclass
class SessionData:
    id: str
    app_name: str
    user_id: str
    history: list = field(default_factory=list)


class RedisSessionService:
    """
    Session service backed by Redis.
    Keeps last MAX_HISTORY_TURNS conversation turns, TTL 1 hour.
    Gracefully falls back to InMemorySessionService if Redis is unavailable.
    """

    def __init__(self, redis_url: str):
        self._fallback = InMemorySessionService()
        self._redis: Optional[redis.Redis] = None
        self._use_redis = False

        try:
            client = redis.Redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=2)
            client.ping()
            self._redis = client
            self._use_redis = True
            logger.info("Redis session service connected: %s", redis_url)
        except Exception as e:
            logger.warning("Redis unavailable (%s) — using InMemorySessionService fallback", e)

    def _session_key(self, session_id: str) -> str:
        return f"masova:session:{session_id}"

    async def create_session(self, app_name: str, user_id: str, session_id: Optional[str] = None, **kwargs) -> SessionData:
        sid = session_id or str(uuid.uuid4())
        session = SessionData(id=sid, app_name=app_name, user_id=user_id)

        if self._use_redis:
            try:
                data = json.dumps({"id": sid, "app_name": app_name, "user_id": user_id, "history": []})
                self._redis.setex(self._session_key(sid), SESSION_TTL_SECONDS, data)
                logger.debug("Created Redis session: %s for user: %s", sid, user_id)
                return session
            except Exception as e:
                logger.warning("Redis write failed (%s) — falling back", e)

        # Fallback
        return await self._fallback.create_session(app_name=app_name, user_id=user_id)

    async def get_session(self, app_name: str, user_id: str, session_id: str, **kwargs) -> Optional[SessionData]:
        if self._use_redis:
            try:
                raw = self._redis.get(self._session_key(session_id))
                if raw:
                    data = json.loads(raw)
                    return SessionData(
                        id=data["id"],
                        app_name=data["app_name"],
                        user_id=data["user_id"],
                        history=data.get("history", [])
                    )
            except Exception as e:
                logger.warning("Redis read failed (%s) — falling back", e)

        return await self._fallback.get_session(app_name=app_name, user_id=user_id, session_id=session_id)

    async def append_turn(self, session_id: str, role: str, text: str) -> None:
        """Append a conversation turn and trim to MAX_HISTORY_TURNS."""
        if not self._use_redis:
            return  # InMemory fallback handles history internally via ADK

        try:
            raw = self._redis.get(self._session_key(session_id))
            if not raw:
                return
            data = json.loads(raw)
            history = data.get("history", [])
            history.append({"role": role, "text": text})
            # Keep only last MAX_HISTORY_TURNS entries
            data["history"] = history[-MAX_HISTORY_TURNS:]
            self._redis.setex(self._session_key(session_id), SESSION_TTL_SECONDS, json.dumps(data))
        except Exception as e:
            logger.warning("Redis history append failed (%s)", e)
