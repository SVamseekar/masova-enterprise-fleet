"""ActionProposal store, normalize, list/resolve API."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from masova_agent.runtime.models import ActionProposal, ProposalStatus, RiskTier
from masova_agent.runtime import proposal_store
from masova_agent.runtime.agent_runtime import get_runtime, reset_runtime_for_tests
from masova_agent.runtime.models import AgentRunRequest
from masova_agent.runtime.idempotency import clear_for_tests


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.setenv("PROPOSAL_DATA_DIR", str(tmp_path / "proposals"))
    proposal_store.clear_for_tests()
    clear_for_tests()
    reset_runtime_for_tests()
    yield
    proposal_store.clear_for_tests()
    clear_for_tests()
    reset_runtime_for_tests()


class TestActionProposalModel:
    def test_canonical_fields(self):
        p = ActionProposal(
            type="DRAFT_PURCHASE_ORDER",
            store_id="DOM001",
            summary="Draft PO",
            rationale="Low stock",
            agent="inventory_reorder",
            idempotency_key="idem:test",
        )
        d = p.to_dict()
        assert d["requires_approval"] is True
        assert d["status"] == "PENDING"
        assert d["proposal_id"]
        assert d["created_at"]
        assert d["idempotency_key"] == "idem:test"
        assert d["risk"] == "PROPOSE"

    def test_from_dict_normalizes(self):
        p = ActionProposal.from_dict({
            "type": "X",
            "store_id": "s1",
            "summary": "s",
            "rationale": "r",
            "idempotency_key": "k1",
        }, agent="kitchen_coach")
        assert p.agent == "kitchen_coach"
        assert p.status == ProposalStatus.PENDING


class TestProposalStore:
    def test_save_list_resolve(self):
        p = ActionProposal(
            type="DRAFT_CHURN_CAMPAIGN",
            store_id="DOM001",
            summary="Win-back",
            rationale="Inactive",
            agent="churn_prevention",
        )
        rec = proposal_store.save_proposal(p)
        assert rec["proposal_id"] == p.proposal_id
        listed = proposal_store.list_proposals(store_id="DOM001", status="PENDING")
        assert any(x["proposal_id"] == p.proposal_id for x in listed)
        resolved = proposal_store.resolve_proposal(p.proposal_id, "APPROVED", note="ok")
        assert resolved["status"] == "APPROVED"
        assert resolved["resolution_note"] == "ok"
        assert resolved["resolved_at"]
        got = proposal_store.get_proposal(p.proposal_id)
        assert got["status"] == "APPROVED"

    def test_resolve_invalid_status(self):
        p = ActionProposal(type="T", store_id="s", summary="s", rationale="r")
        proposal_store.save_proposal(p)
        with pytest.raises(ValueError):
            proposal_store.resolve_proposal(p.proposal_id, "EXECUTE")

    def test_notify_payload(self):
        p = ActionProposal(
            type="T", store_id="s", summary="Sum", rationale="Why", agent="a"
        )
        n = proposal_store.notify_payload_for(p)
        assert n["proposal_id"] == p.proposal_id
        assert n["requires_approval"] is True


class TestRuntimePersistsProposals:
    @pytest.mark.asyncio
    async def test_run_saves_proposals(self):
        async def fb():
            return {
                "status": "ok",
                "proposals": [{
                    "type": "DRAFT_PURCHASE_ORDER",
                    "store_id": "DOM001",
                    "summary": "PO",
                    "rationale": "low",
                    "requires_approval": True,
                }],
            }

        runtime = get_runtime()
        res = await runtime.run(
            AgentRunRequest(
                agent_name="inventory_reorder",
                trigger_type="manual",
                store_id="DOM001",
                prefer_llm=False,
                fallback=fb,
            )
        )
        assert len(res.proposals) == 1
        assert res.proposals[0].agent == "inventory_reorder"
        stored = proposal_store.get_proposal(res.proposals[0].proposal_id)
        assert stored is not None
        assert stored["status"] == "PENDING"


class TestProposalAPI:
    def test_list_and_resolve_endpoints(self, monkeypatch):
        monkeypatch.setenv("AGENT_TRIGGER_API_KEY", "test-key")
        from masova_agent.main import app

        p = ActionProposal(
            type="SUGGEST_PRICE_ADJUSTMENT",
            store_id="DOM001",
            summary=" +12%",
            rationale="overload",
            agent="dynamic_pricing",
        )
        proposal_store.save_proposal(p)

        client = TestClient(app)
        r = client.get(
            "/agent/proposals",
            headers={"X-Agent-Api-Key": "test-key"},
            params={"storeId": "DOM001"},
        )
        assert r.status_code == 200
        assert any(x["proposal_id"] == p.proposal_id for x in r.json()["proposals"])

        r2 = client.post(
            f"/agent/proposals/{p.proposal_id}/resolve",
            headers={"X-Agent-Api-Key": "test-key"},
            json={"status": "REJECTED", "note": "not needed"},
        )
        assert r2.status_code == 200
        assert r2.json()["status"] == "REJECTED"

    def test_list_requires_key(self, monkeypatch):
        monkeypatch.setenv("AGENT_TRIGGER_API_KEY", "test-key")
        from masova_agent.main import app

        client = TestClient(app)
        r = client.get("/agent/proposals")
        assert r.status_code in (401, 403, 422)


class TestNotifyIncludesProposal:
    @pytest.mark.asyncio
    async def test_notify_managers_embeds_proposal_id(self):
        from masova_agent.tools import ops_tools

        captured = []

        async def fake_get(client, path, params=None):
            return 200, {"content": [{"id": "mgr-1"}]}

        async def fake_post(client, path, body=None):
            captured.append(body)
            return 201, {}

        with patch.object(ops_tools, "_require_token", return_value=None), patch.object(
            ops_tools, "get_json", side_effect=fake_get
        ), patch.object(ops_tools, "post_json", side_effect=fake_post):
            await ops_tools.notify_managers(
                store_id="DOM001",
                message="Please review",
                proposal_id="prop-123",
                proposal_summary="Draft PO",
                rationale="Low flour",
            )
        assert captured
        assert "prop-123" in captured[0]["message"]
        assert captured[0]["data"]["proposal_id"] == "prop-123"
