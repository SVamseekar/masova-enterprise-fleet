"""
Unit & integration tests for Phase 6: In-Repo Fleet Console & Proposal Review API.
"""

from __future__ import annotations

import datetime
from datetime import timezone
import sqlite3
import pytest
from fastapi.testclient import TestClient

from masova_agent.main import app
from masova_agent.runtime import proposal_store, proposal_expiry
from masova_agent.runtime.models import ActionProposal, ProposalStatus


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def seeded_db(tmp_path):
    db_file = tmp_path / "masova_demo.sqlite"
    from scripts.seed_demo_data import seed
    seed(str(db_file))
    return str(db_file)


@pytest.fixture(autouse=True)
def _clean_proposals(tmp_path, monkeypatch):
    monkeypatch.setenv("PROPOSAL_DATA_DIR", str(tmp_path / "proposals"))
    monkeypatch.setenv("AGENT_TRIGGER_API_KEY", "test-key")
    proposal_store.clear_for_tests()
    yield
    proposal_store.clear_for_tests()


def test_console_endpoint_serves_html(client):
    res = client.get("/console")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    body = res.text
    assert "Masova Agent Fleet" in body
    assert "Oberkampf" in body
    assert "Google ADK" in body


def test_agents_registry_endpoint(client):
    res = client.get("/agents")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) == 8
    agent_ids = {a["id"] for a in data}
    assert "inventory_reorder" in agent_ids
    assert "demand_forecast" in agent_ids
    assert "churn_prevention" in agent_ids


def test_proposals_type_filter(client):
    p1 = ActionProposal(
        type="DRAFT_PURCHASE_ORDER",
        store_id="68a1f2c9e4b0a1234567890a",
        summary="PO Mozzarella",
        rationale="Low stock",
        agent="inventory_reorder",
        idempotency_key="idem:po:1",
    )
    p2 = ActionProposal(
        type="DRAFT_CHURN_CAMPAIGN",
        store_id="68a1f2c9e4b0a1234567890a",
        summary="Churn campaign",
        rationale="Lapsed customers",
        agent="churn_prevention",
        idempotency_key="idem:churn:1",
    )
    proposal_store.save_proposal(p1)
    proposal_store.save_proposal(p2)

    headers = {"X-Agent-Api-Key": "test-key"}

    # 1. Filter by type=DRAFT_PURCHASE_ORDER
    res = client.get("/agent/proposals?type=DRAFT_PURCHASE_ORDER", headers=headers)
    assert res.status_code == 200
    props = res.json()["proposals"]
    assert len(props) == 1
    assert props[0]["type"] == "DRAFT_PURCHASE_ORDER"

    # 2. Filter by type=DRAFT_CHURN_CAMPAIGN
    res2 = client.get("/agent/proposals?type=DRAFT_CHURN_CAMPAIGN", headers=headers)
    assert res2.status_code == 200
    props2 = res2.json()["proposals"]
    assert len(props2) == 1
    assert props2[0]["type"] == "DRAFT_CHURN_CAMPAIGN"


def test_resolve_proposal_with_apply_in_demo_mode(seeded_db, monkeypatch, client):
    monkeypatch.setenv("DEMO_DB_PATH", str(seeded_db))
    monkeypatch.setenv("DEMO_MODE", "true")

    # Insert DRAFT PO in demo DB
    conn = sqlite3.connect(seeded_db)
    conn.execute(
        "INSERT INTO purchase_orders (id, store_id, supplier_id, status, auto_generated, created_at) VALUES ('PO-RES-1', '68a1f2c9e4b0a1234567890a', 'sup-1', 'DRAFT', 1, '2026-08-22')"
    )
    conn.commit()

    prop = ActionProposal(
        type="DRAFT_PURCHASE_ORDER",
        store_id="68a1f2c9e4b0a1234567890a",
        summary="PO Draft",
        rationale="Low stock",
        agent="inventory_reorder",
        payload={"po_id": "PO-RES-1"},
        idempotency_key="idem:po:res:1",
    )
    saved = proposal_store.save_proposal(prop)
    pid = saved["proposal_id"]

    headers = {"X-Agent-Api-Key": "test-key"}

    # Resolve proposal via POST /agent/proposals/{id}/resolve
    res = client.post(
        f"/agent/proposals/{pid}/resolve",
        headers=headers,
        json={"status": "APPROVED", "note": "Approved by manager in console"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "APPROVED"
    assert data.get("applied") is True

    # Check that SQLite row was updated
    row = conn.execute("SELECT status, approved_by FROM purchase_orders WHERE id = 'PO-RES-1'").fetchone()
    assert row[0] == "PENDING_APPROVAL"
    assert row[1] == "demo-manager"



def test_sweep_expired_proposals():
    # 1. Fresh proposal (pending, now)
    p_fresh = ActionProposal(
        type="DRAFT_PURCHASE_ORDER",
        store_id="68a1f2c9e4b0a1234567890a",
        summary="Fresh PO",
        rationale="Just created",
        agent="inventory_reorder",
        idempotency_key="idem:fresh",
    )
    proposal_store.save_proposal(p_fresh)

    # 2. Stale proposal (4 days old)
    old_time = (datetime.datetime.now(timezone.utc) - datetime.timedelta(days=4)).isoformat()
    p_stale = ActionProposal(
        type="DRAFT_CHURN_CAMPAIGN",
        store_id="68a1f2c9e4b0a1234567890a",
        summary="Stale Campaign",
        rationale="Old",
        agent="churn_prevention",
        idempotency_key="idem:stale",
        created_at=old_time,
    )
    proposal_store.save_proposal(p_stale)

    # Run sweep with max_age_hours=72
    expired = proposal_expiry.sweep_expired(max_age_hours=72)
    assert expired == 1

    # Check status
    fresh_check = proposal_store.get_proposal(p_fresh.proposal_id)
    assert fresh_check["status"] == "PENDING"

    stale_check = proposal_store.get_proposal(p_stale.proposal_id)
    assert stale_check["status"] == "EXPIRED"
    assert "Auto-expired" in stale_check.get("resolution_note", "")
