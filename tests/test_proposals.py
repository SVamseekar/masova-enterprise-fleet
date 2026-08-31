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


class TestOpenQueueLifecycle:
    def test_notify_is_side_effect(self):
        assert proposal_store.is_side_effect({"type": "NOTIFY_MANAGERS"})
        assert not proposal_store.is_side_effect({"type": "DRAFT_PURCHASE_ORDER"})

    def test_snapshot_run_replaces_older_pending(self):
        older = ActionProposal(
            type="DRAFT_PURCHASE_ORDER",
            store_id="DOM001",
            summary="Old PO",
            rationale="stale",
            agent="inventory_reorder",
        )
        newer = ActionProposal(
            type="DRAFT_PURCHASE_ORDER",
            store_id="DOM001",
            summary="New PO mozzarella",
            rationale="low stock",
            agent="inventory_reorder",
        )
        other_store = ActionProposal(
            type="DRAFT_PURCHASE_ORDER",
            store_id="DOM002",
            summary="Other store PO",
            rationale="low stock",
            agent="inventory_reorder",
        )
        rec_old = proposal_store.save_proposal(older)
        rec_old["run_id"] = "run-old"
        proposal_store.save_proposal(rec_old)
        rec_new = proposal_store.save_proposal(newer)
        rec_new["run_id"] = "run-new"
        proposal_store.save_proposal(rec_new)
        proposal_store.save_proposal(other_store)

        n = proposal_store.supersede_stale_pending(
            store_id="DOM001",
            agent="inventory_reorder",
            keep_ids={newer.proposal_id},
            keep_run_id="run-new",
        )
        assert n == 1
        assert proposal_store.get_proposal(older.proposal_id)["status"] == "SUPERSEDED"
        assert proposal_store.get_proposal(newer.proposal_id)["status"] == "PENDING"
        assert proposal_store.get_proposal(other_store.proposal_id)["status"] == "PENDING"

    def test_review_supersede_is_per_review_id(self):
        a = ActionProposal(
            type="DRAFT_REVIEW_REPLY",
            store_id="DOM001",
            summary="Draft A",
            rationale="1 star",
            agent="review_response",
            payload={"review_id": "REV-A"},
        )
        b = ActionProposal(
            type="DRAFT_REVIEW_REPLY",
            store_id="DOM001",
            summary="Draft B",
            rationale="2 star",
            agent="review_response",
            payload={"review_id": "REV-B"},
        )
        proposal_store.save_proposal(a)
        proposal_store.save_proposal(b)
        n = proposal_store.supersede_stale_pending(
            store_id="DOM001",
            agent="review_response",
            keep_ids={b.proposal_id},
            keep_run_id="run-b",
            review_id="REV-B",
        )
        assert n == 0
        assert proposal_store.get_proposal(a.proposal_id)["status"] == "PENDING"

    def test_sweep_closes_notify_and_keeps_latest_run(self):
        notify = ActionProposal(
            type="NOTIFY_MANAGERS",
            store_id="DOM001",
            summary="Alert",
            rationale="ping",
            agent="inventory_reorder",
        )
        old_po = ActionProposal(
            type="DRAFT_PURCHASE_ORDER",
            store_id="DOM001",
            summary="Old",
            rationale="old",
            agent="inventory_reorder",
        )
        new_po = ActionProposal(
            type="DRAFT_PURCHASE_ORDER",
            store_id="DOM001",
            summary="Mozzarella",
            rationale="low",
            agent="inventory_reorder",
        )
        rec_old = proposal_store.save_proposal(old_po)
        rec_old["run_id"] = "r1"
        rec_old["created_at"] = "2026-08-30T10:00:00+00:00"
        proposal_store.save_proposal(rec_old)
        rec_new = proposal_store.save_proposal(new_po)
        rec_new["run_id"] = "r2"
        rec_new["created_at"] = "2026-08-31T10:00:00+00:00"
        proposal_store.save_proposal(rec_new)
        proposal_store.save_proposal(notify)

        swept = proposal_store.sweep_stale_open_queue()
        assert swept["notify"] == 1
        assert swept["stale"] == 1
        pending = proposal_store.list_proposals(status="PENDING", exclude_side_effects=True, limit=0)
        assert [p["proposal_id"] for p in pending] == [new_po.proposal_id]


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

    @pytest.mark.asyncio
    async def test_runtime_skips_notify_and_supersedes_prior_run(self):
        runtime = get_runtime()

        async def first():
            return {
                "status": "ok",
                "proposals": [{
                    "type": "DRAFT_PURCHASE_ORDER",
                    "store_id": "DOM001",
                    "summary": "Old PO",
                    "rationale": "low",
                    "requires_approval": True,
                }],
            }

        async def second():
            return {
                "status": "ok",
                "proposals": [
                    {
                        "type": "DRAFT_PURCHASE_ORDER",
                        "store_id": "DOM001",
                        "summary": "Mozzarella 15kg",
                        "rationale": "6.2 of 10",
                        "requires_approval": True,
                        "payload": {"items": [{"itemName": "Mozzarella (kg)", "quantity": 15}]},
                    },
                    {
                        "type": "NOTIFY_MANAGERS",
                        "store_id": "DOM001",
                        "summary": "Low Stock Alert",
                        "rationale": "ping",
                        "requires_approval": True,
                        "payload": {"sent": 1, "notification_type": "low_stock_alert"},
                    },
                ],
            }

        first_res = await runtime.run(
            AgentRunRequest(
                agent_name="inventory_reorder",
                trigger_type="manual",
                store_id="DOM001",
                prefer_llm=False,
                fallback=first,
            )
        )
        second_res = await runtime.run(
            AgentRunRequest(
                agent_name="inventory_reorder",
                trigger_type="manual",
                store_id="DOM001",
                prefer_llm=False,
                fallback=second,
            )
        )
        assert [p.type for p in second_res.proposals] == ["DRAFT_PURCHASE_ORDER"]
        pending = proposal_store.list_proposals(
            store_id="DOM001", status="PENDING", agent="inventory_reorder", limit=0
        )
        assert len(pending) == 1
        assert pending[0]["summary"] == "Mozzarella 15kg"
        assert proposal_store.get_proposal(first_res.proposals[0].proposal_id)["status"] == "SUPERSEDED"

    @pytest.mark.asyncio
    async def test_run_copies_po_evidence_from_low_stock_tool_result(self):
        from masova_agent.runtime.agent_runtime import AgentRuntime
        from masova_agent.runtime.ops_llm import run_scripted_tool_loop

        async def list_low_stock(store_id: str = ""):
            return {
                "ok": True,
                "items": [{
                    "id": "inv-low-1",
                    "store_id": store_id,
                    "item_name": "Flour",
                    "current_stock": 6.2,
                    "minimum_stock": 10,
                    "reorder_quantity": 25,
                    "primary_supplier_id": "sup-1",
                }],
            }

        async def create_draft_po(store_id: str, supplier_id: str, items=None, **_kwargs):
            return {
                "ok": True,
                "proposal": {
                    "type": "DRAFT_PURCHASE_ORDER",
                    "store_id": store_id,
                    "summary": "Draft PO",
                    "rationale": "Restock low inventory",
                    "requires_approval": True,
                    "payload": {
                        "supplier_id": supplier_id,
                        "items": items or [],
                    },
                },
            }

        tools = {
            "list_low_stock": list_low_stock,
            "create_draft_po": create_draft_po,
        }
        plan = [
            {"tool": "list_low_stock", "args": {"store_id": "DOM001"}},
            {
                "tool": "create_draft_po",
                "args": {
                    "store_id": "DOM001",
                    "supplier_id": "sup-1",
                    "items": [{"inventoryItemId": "inv-low-1", "itemName": "Flour", "quantity": 25}],
                },
            },
        ]

        runtime = AgentRuntime()
        result = await runtime.run(AgentRunRequest(
            agent_name="inventory_reorder",
            trigger_type="manual",
            store_id="DOM001",
            allowed_tools=list(tools.keys()),
            prefer_llm=True,
            llm_runner=lambda request: run_scripted_tool_loop(request, plan, tools),
        ))

        proposal = next(p for p in result.proposals if p.type == "DRAFT_PURCHASE_ORDER")
        assert proposal.evidence == [{
            "tool": "list_low_stock",
            "row_id": "inv-low-1",
            "field": "currentStock",
            "value": 6.2,
        }]

        stored = proposal_store.get_proposal(proposal.proposal_id)
        assert stored is not None
        assert stored["evidence"] == proposal.evidence


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
