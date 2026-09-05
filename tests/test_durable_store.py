"""Firestore durable store — in-memory fake, no live GCP."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from masova_agent.runtime import durable, proposal_store, run_store
from masova_agent.runtime.models import ActionProposal


class _FakeSnap:
    def __init__(self, doc_id, data, exists=True):
        self.id = doc_id
        self._data = data
        self.exists = exists

    def to_dict(self):
        return dict(self._data)


class _FakeCollection:
    def __init__(self, bucket):
        self._bucket = bucket

    def document(self, doc_id):
        coll = self
        bid = doc_id

        class _Doc:
            def set(self, data):
                coll._bucket[bid] = dict(data)

            def get(self):
                if bid not in coll._bucket:
                    return _FakeSnap(bid, {}, exists=False)
                return _FakeSnap(bid, coll._bucket[bid], exists=True)

        return _Doc()

    def stream(self):
        for k, v in list(self._bucket.items()):
            yield _FakeSnap(k, v, exists=True)


class _FakeClient:
    def __init__(self):
        self.proposals = {}
        self.runs = {}

    def collection(self, name):
        if name == durable.PROPOSALS:
            return _FakeCollection(self.proposals)
        return _FakeCollection(self.runs)


def test_firestore_enabled_env(monkeypatch):
    monkeypatch.delenv("DURABLE_STORE", raising=False)
    durable.reset_client_for_tests()
    assert durable.firestore_enabled() is False
    monkeypatch.setenv("DURABLE_STORE", "firestore")
    assert durable.firestore_enabled() is True


def test_proposal_survives_memory_clear(monkeypatch):
    monkeypatch.setenv("DURABLE_STORE", "firestore")
    fake = _FakeClient()
    durable.reset_client_for_tests()
    monkeypatch.setattr(durable, "get_client", lambda: fake)
    proposal_store.clear_for_tests()
    monkeypatch.setattr(durable, "get_client", lambda: fake)

    p = ActionProposal(
        type="DRAFT_PURCHASE_ORDER",
        store_id="STORE1",
        summary="PO",
        rationale="low stock",
        agent="inventory_reorder",
    )
    proposal_store.save_proposal(p)
    assert p.proposal_id in fake.proposals

    proposal_store.clear_for_tests()
    monkeypatch.setattr(durable, "get_client", lambda: fake)
    monkeypatch.setenv("DURABLE_STORE", "firestore")
    listed = proposal_store.list_proposals(store_id="STORE1", status="PENDING")
    assert any(r["proposal_id"] == p.proposal_id for r in listed)


def test_resolve_persists(monkeypatch):
    monkeypatch.setenv("DURABLE_STORE", "firestore")
    fake = _FakeClient()
    durable.reset_client_for_tests()
    monkeypatch.setattr(durable, "get_client", lambda: fake)
    proposal_store.clear_for_tests()
    monkeypatch.setattr(durable, "get_client", lambda: fake)

    p = ActionProposal(
        type="DRAFT_CHURN_CAMPAIGN",
        store_id="STORE1",
        summary="Win-back",
        rationale="inactive",
        agent="churn_prevention",
    )
    proposal_store.save_proposal(p)
    proposal_store.resolve_proposal(p.proposal_id, "APPROVED", note="ok")
    packed = fake.proposals[p.proposal_id]
    rec = json.loads(packed["record"])
    assert rec["status"] == "APPROVED"
    assert rec["resolution_note"] == "ok"


def test_run_record_persists(monkeypatch):
    monkeypatch.setenv("DURABLE_STORE", "firestore")
    fake = _FakeClient()
    durable.reset_client_for_tests()
    monkeypatch.setattr(durable, "get_client", lambda: fake)
    run_store.clear_for_tests()
    monkeypatch.setattr(durable, "get_client", lambda: fake)

    rec = run_store.record_run(
        {"agent": "demand_forecast", "store_id": "STORE1", "status": "ok", "run_id": "r1", "at": "t"}
    )
    assert rec["record_hash"]
    assert "r1" in fake.runs

    run_store.clear_for_tests()
    monkeypatch.setattr(durable, "get_client", lambda: fake)
    rows = run_store.list_runs(agent="demand_forecast")
    assert any(r.get("run_id") == "r1" for r in rows)
