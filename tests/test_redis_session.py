"""Tests for Redis session service"""
import sys
import os
import pytest
from unittest.mock import MagicMock, patch

# Ensure src/ package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import masova_agent.core.redis_session_service  # noqa: F401 — force module registration for patching


@pytest.mark.asyncio
async def test_create_session_stores_in_redis():
    """Session creation should store session data in Redis"""
    mock_redis = MagicMock()
    mock_redis.ping = MagicMock(return_value=True)
    mock_redis.setex = MagicMock(return_value=True)
    mock_redis.get = MagicMock(return_value=None)

    with patch("masova_agent.core.redis_session_service.redis.Redis") as mock_cls:
        mock_cls.from_url = MagicMock(return_value=mock_redis)
        from masova_agent.core.redis_session_service import RedisSessionService
        service = RedisSessionService(redis_url="redis://localhost:6379/1")
        session = await service.create_session(app_name="test_app", user_id="user_123")

    assert session.id is not None
    assert mock_redis.setex.called


@pytest.mark.asyncio
async def test_session_ttl_is_one_hour():
    """Session TTL should be 3600 seconds (1 hour)"""
    mock_redis = MagicMock()
    mock_redis.ping = MagicMock(return_value=True)
    mock_redis.setex = MagicMock(return_value=True)

    with patch("masova_agent.core.redis_session_service.redis.Redis") as mock_cls:
        mock_cls.from_url = MagicMock(return_value=mock_redis)
        from masova_agent.core.redis_session_service import RedisSessionService
        service = RedisSessionService(redis_url="redis://localhost:6379/1")
        await service.create_session(app_name="test_app", user_id="user_123")

    call_args = mock_redis.setex.call_args
    ttl = call_args[0][1]  # Second positional arg is TTL
    assert ttl == 3600


@pytest.mark.asyncio
async def test_fallback_to_in_memory_when_redis_unavailable():
    """Should fall back to InMemorySessionService if Redis is down"""
    with patch("masova_agent.core.redis_session_service.redis.Redis") as mock_cls:
        mock_cls.from_url.side_effect = Exception("Redis connection refused")
        from masova_agent.core.redis_session_service import RedisSessionService
        service = RedisSessionService(redis_url="redis://localhost:6379/1")

    assert service is not None
    session = await service.create_session(app_name="test_app", user_id="user_123")
    assert session.id is not None
