"""Manager Gemini Chat door — API key, not customer JWT."""
import json
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


def test_manager_chat_requires_api_key(monkeypatch):
    monkeypatch.setenv("AGENT_TRIGGER_API_KEY", "test-key")
    from masova_agent.main import app

    client = TestClient(app)
    resp = client.post("/agent/manager/chat", json={"message": "hello"})
    assert resp.status_code == 401


def test_manager_chat_rejects_customer_style_unauthed(monkeypatch):
    monkeypatch.delenv("AGENT_API_KEYS", raising=False)
    monkeypatch.setenv("AGENT_TRIGGER_API_KEY", "mgr-key")
    from masova_agent.main import app

    client = TestClient(app)
    with patch(
        "masova_agent.agents.manager_chat_agent.run_manager_chat",
        new_callable=AsyncMock,
        return_value={"reply": "Stock looks fine.", "sessionId": "s1"},
    ):
        resp = client.post(
            "/agent/manager/chat",
            headers={"X-Agent-Api-Key": "mgr-key"},
            json={"message": "check inventory", "storeId": "68a1f2c9e4b0a1234567890a"},
        )
    assert resp.status_code == 200
    assert resp.json()["reply"] == "Stock looks fine."


def test_manager_chat_wrong_scope_is_403(monkeypatch):
    monkeypatch.setenv("AGENT_API_KEYS", json.dumps([
        {"key": "inv-only", "scopes": ["trigger:inventory_reorder"]},
    ]))
    from masova_agent.main import app

    client = TestClient(app)
    resp = client.post(
        "/agent/manager/chat",
        headers={"X-Agent-Api-Key": "inv-only"},
        json={"message": "hello"},
    )
    assert resp.status_code == 403


def test_focus_store_list_does_not_fall_through():
    from masova_agent.tools.ops_http import focus_store_list

    stores = [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}]
    assert focus_store_list(stores, None) == stores
    assert focus_store_list(stores, "b") == [{"id": "b", "name": "B"}]
    scoped = focus_store_list(stores, "missing")
    assert len(scoped) == 1
    assert scoped[0]["id"] == "missing"
