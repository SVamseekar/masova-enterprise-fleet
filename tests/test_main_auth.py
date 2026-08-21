"""
Integration tests for auth gating on the FastAPI HTTP surface (main.py).

Uses TestClient without entering the lifespan context manager, so the
scheduler/RabbitMQ consumer never start — these tests only exercise
request-level dependency injection (auth), not the full app lifecycle.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import jwt
import pytest
from fastapi.testclient import TestClient

SECRET = "test-secret-at-least-64-characters-long-for-hs512-aaaaaaaaaaaaaaaaaaaaaa"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SECRET)
    monkeypatch.setenv("AGENT_TRIGGER_API_KEY", "trigger-secret")


@pytest.fixture
def client():
    from masova_agent.main import app
    return TestClient(app, raise_server_exceptions=False)


def _customer_token() -> str:
    return jwt.encode(
        {"sub": "cust-123", "userType": "CUSTOMER", "exp": int(time.time()) + 3600},
        SECRET, algorithm="HS512",
    )


class TestChatAuth:
    def test_chat_without_auth_header_returns_401(self, client):
        resp = client.post("/agent/chat", json={"message": "hi"})
        assert resp.status_code == 401

    def test_chat_with_invalid_token_returns_401(self, client):
        resp = client.post(
            "/agent/chat",
            json={"message": "hi"},
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        assert resp.status_code == 401

    def test_chat_request_body_no_longer_accepts_customer_id(self, client):
        """customerId must not be a usable input — identity comes only from the JWT."""
        from masova_agent.main import ChatRequest
        assert "customerId" not in ChatRequest.model_fields


class TestTriggerEndpointAuth:
    @pytest.mark.parametrize("path", [
        "/agents/demand-forecast/trigger",
        "/agents/inventory-reorder/trigger",
        "/agents/churn-prevention/trigger",
        "/agents/shift-optimisation/trigger",
        "/agents/kitchen-coach/trigger",
        "/agents/dynamic-pricing/trigger",
    ])
    def test_trigger_without_api_key_returns_401(self, client, path):
        resp = client.post(path)
        assert resp.status_code == 401

    @pytest.mark.parametrize("path", [
        "/agents/demand-forecast/trigger",
        "/agents/inventory-reorder/trigger",
        "/agents/churn-prevention/trigger",
    ])
    def test_trigger_with_wrong_api_key_returns_401(self, client, path):
        resp = client.post(path, headers={"X-Agent-Api-Key": "wrong"})
        assert resp.status_code == 401

    def test_review_response_trigger_requires_api_key(self, client):
        resp = client.post("/agents/review-response/trigger", json={"rating": 2})
        assert resp.status_code == 401


def test_health_does_not_require_auth(client):
    resp = client.get("/health")
    assert resp.status_code == 200
