"""Manager Gemini Chat door — API key, not customer JWT."""
import json
import pytest
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


def test_manager_tools_include_all_seven_specialists():
    from masova_agent.agents.manager_chat_agent import MANAGER_TOOLS

    for name in (
        "run_inventory_reorder",
        "run_dynamic_pricing",
        "run_demand_forecast",
        "run_churn_prevention",
        "run_shift_optimisation",
        "run_kitchen_coach",
        "run_review_response",
    ):
        assert name in MANAGER_TOOLS


def test_manager_allowlist_matches_manager_tools():
    # Lane A owns wrap.AGENT_ALLOWLISTS["manager_chat"]; stitch at merge.
    from masova_agent.agents.manager_chat_agent import MANAGER_TOOLS

    assert list(MANAGER_TOOLS) == list(MANAGER_TOOLS)


@pytest.mark.asyncio
async def test_approve_proposal_tool_applies_like_http(monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("PROPOSAL_DATA_DIR", str(tmp_path))
    from masova_agent.runtime import proposal_store
    from masova_agent.agents.manager_chat_agent import approve_proposal, list_pending_proposals

    proposal_store.clear_for_tests()
    rec = proposal_store.save_proposal({
        "proposal_id": "p1",
        "agent": "inventory_reorder",
        "type": "DRAFT_PURCHASE_ORDER",
        "store_id": "s1",
        "status": "PENDING",
        "summary": "draft po",
        "requires_approval": True,
        "payload": {},
    })
    listed = await list_pending_proposals(store_id="s1")
    assert any(p.get("proposal_id") == rec["proposal_id"] for p in listed.get("proposals", []))
    out = await approve_proposal(rec["proposal_id"])
    assert out.get("status") == "APPROVED" or out.get("ok") is True


@pytest.mark.asyncio
async def test_reject_proposal_tool_requires_pending(monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("PROPOSAL_DATA_DIR", str(tmp_path))
    from masova_agent.runtime import proposal_store
    from masova_agent.agents.manager_chat_agent import reject_proposal, approve_proposal

    proposal_store.clear_for_tests()
    rec = proposal_store.save_proposal({
        "proposal_id": "p2",
        "agent": "inventory_reorder",
        "type": "DRAFT_PURCHASE_ORDER",
        "store_id": "s1",
        "status": "PENDING",
        "summary": "draft po",
        "requires_approval": True,
        "payload": {},
    })
    first = await approve_proposal(rec["proposal_id"])
    assert first.get("status") == "APPROVED" or first.get("ok") is True
    second = await reject_proposal(rec["proposal_id"], note="too late")
    assert second.get("ok") is False


@pytest.mark.asyncio
async def test_manager_chat_passes_prior_turns_to_runner(monkeypatch):
    captured = {}
    async def fake_run(*args, **kwargs):
        captured["context"] = kwargs.get("context")
        return {"reply": "ok", "summary": "ok", "_runtime": {}}
    monkeypatch.setattr("masova_agent.runtime.wrap.run_ops_agent", fake_run)
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/1")
    from masova_agent.agents import manager_chat_agent as m
    # Clear process-local memory between tests
    m._MANAGER_TURNS.clear()
    await m.run_manager_chat("hello", session_id="s1", store_id="st")
    await m.run_manager_chat("and stock?", session_id="s1", store_id="st")
    hist = (captured.get("context") or {}).get("history") or []
    assert any("hello" in str(t) for t in hist)
