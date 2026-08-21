"""
Unit tests for masova_agent.auth — JWT verification and identity binding.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import os
import time

import jwt
import pytest
from fastapi import HTTPException

from masova_agent.auth import (
    AgentIdentity,
    bind_identity,
    get_current_identity,
    reset_identity,
    verify_customer_jwt,
    verify_trigger_api_key,
)

SECRET = "test-secret-at-least-64-characters-long-for-hs512-aaaaaaaaaaaaaaaaaaaaaa"


@pytest.fixture(autouse=True)
def _jwt_secret_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SECRET)


def _make_token(**claims) -> str:
    payload = {"sub": "cust-123", "userType": "CUSTOMER", "exp": int(time.time()) + 3600}
    payload.update(claims)
    return jwt.encode(payload, SECRET, algorithm="HS512")


class TestVerifyCustomerJwt:
    @pytest.mark.asyncio
    async def test_valid_token_returns_identity(self):
        token = _make_token()
        identity = await verify_customer_jwt(authorization=f"Bearer {token}")
        assert identity.user_id == "cust-123"
        assert identity.user_type == "CUSTOMER"

    @pytest.mark.asyncio
    async def test_missing_header_raises_401(self):
        with pytest.raises(HTTPException) as exc:
            await verify_customer_jwt(authorization="")
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_malformed_header_raises_401(self):
        with pytest.raises(HTTPException) as exc:
            await verify_customer_jwt(authorization="NotBearer abc")
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_expired_token_raises_401(self):
        token = jwt.encode(
            {"sub": "cust-123", "userType": "CUSTOMER", "exp": int(time.time()) - 10},
            SECRET, algorithm="HS512",
        )
        with pytest.raises(HTTPException) as exc:
            await verify_customer_jwt(authorization=f"Bearer {token}")
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_tampered_signature_raises_401(self):
        token = _make_token()
        tampered = token[:-4] + "abcd"
        with pytest.raises(HTTPException) as exc:
            await verify_customer_jwt(authorization=f"Bearer {tampered}")
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_secret_raises_401(self):
        token = jwt.encode({"sub": "cust-123", "exp": int(time.time()) + 3600}, "wrong-secret-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", algorithm="HS512")
        with pytest.raises(HTTPException) as exc:
            await verify_customer_jwt(authorization=f"Bearer {token}")
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_subject_claim_raises_401(self):
        token = jwt.encode({"userType": "CUSTOMER", "exp": int(time.time()) + 3600}, SECRET, algorithm="HS512")
        with pytest.raises(HTTPException) as exc:
            await verify_customer_jwt(authorization=f"Bearer {token}")
        assert exc.value.status_code == 401


class TestIdentityBinding:
    def test_get_current_identity_without_binding_raises(self):
        with pytest.raises(RuntimeError):
            get_current_identity()

    def test_bind_and_read_identity(self):
        identity = AgentIdentity(user_id="u1", user_type="CUSTOMER", store_id=None, raw_token="t")
        token = bind_identity(identity)
        try:
            assert get_current_identity().user_id == "u1"
        finally:
            reset_identity(token)
        with pytest.raises(RuntimeError):
            get_current_identity()


class TestVerifyTriggerApiKey:
    @pytest.mark.asyncio
    async def test_correct_key_passes(self, monkeypatch):
        monkeypatch.setenv("AGENT_TRIGGER_API_KEY", "secret-key")
        await verify_trigger_api_key(x_agent_api_key="secret-key")  # no raise

    @pytest.mark.asyncio
    async def test_missing_key_raises_401(self, monkeypatch):
        monkeypatch.setenv("AGENT_TRIGGER_API_KEY", "secret-key")
        with pytest.raises(HTTPException) as exc:
            await verify_trigger_api_key(x_agent_api_key="")
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_key_raises_401(self, monkeypatch):
        monkeypatch.setenv("AGENT_TRIGGER_API_KEY", "secret-key")
        with pytest.raises(HTTPException) as exc:
            await verify_trigger_api_key(x_agent_api_key="wrong")
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_unconfigured_key_raises_503(self, monkeypatch):
        monkeypatch.delenv("AGENT_TRIGGER_API_KEY", raising=False)
        with pytest.raises(HTTPException) as exc:
            await verify_trigger_api_key(x_agent_api_key="anything")
        assert exc.value.status_code == 503
