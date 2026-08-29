"""
Unit & integration tests for Phase 6: In-Repo Fleet Console & Proposal Review API.
"""

from __future__ import annotations

import datetime
from datetime import timezone
import json
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
    monkeypatch.delenv("AGENT_API_KEYS", raising=False)
    monkeypatch.setenv("AGENT_TRIGGER_API_KEY", "test-key")
    proposal_store.clear_for_tests()
    yield
    proposal_store.clear_for_tests()


def test_console_endpoint_serves_html(client):
    res = client.get("/console")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    body = res.text
    assert "MaSoVa AI" in body
    assert "Oberkampf" in body
    assert "Needs your OK" in body
    assert "Run inventory" in body
    assert "Pricing signal" in body
    assert "Store proof" in body
    assert 'class="console-shell"' in body
    assert "function runInventory" in body
    assert "function pricingSignal" in body
    assert "function storeProof" in body
    assert "function proposalEvidenceHtml" in body
    assert "proposalEvidenceHtml(proposal)" in body
    assert "/agents/inventory-reorder/trigger" in body
    assert "/agents/dynamic-pricing/trigger" in body
    assert "/agent/demo/tables/inventory?store_id=" in body
    assert "function loadAgentsRail" in body
    assert "System healthy" not in body


def test_agents_registry_requires_key(client):
    res = client.get("/agents")
    assert res.status_code == 401


def test_demo_tables_requires_key(client, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    res = client.get("/agent/demo/tables/stores")
    assert res.status_code == 401


def test_agents_registry_endpoint(client):
    headers = {"X-Agent-Api-Key": "test-key"}
    res = client.get("/agents", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body, dict)
    assert "agents" in body
    data = body["agents"]
    assert isinstance(data, list)
    assert len(data) == 9
    agent_ids = {a["id"] for a in data}
    assert "inventory_reorder" in agent_ids
    assert "demand_forecast" in agent_ids
    assert "churn_prevention" in agent_ids
    assert "manager_chat" in agent_ids


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


def test_client_cannot_post_expired(client):
    p = ActionProposal(
        type="DRAFT_PURCHASE_ORDER",
        store_id="68a1f2c9e4b0a1234567890a",
        summary="Test PO",
        rationale="Low stock",
        agent="inventory_reorder",
        idempotency_key="idem:exp:1",
    )
    saved = proposal_store.save_proposal(p)
    pid = saved["proposal_id"]

    headers = {"X-Agent-Api-Key": "test-key"}
    res = client.post(
        f"/agent/proposals/{pid}/resolve",
        headers=headers,
        json={"status": "EXPIRED", "note": "Client trying to expire"},
    )
    assert res.status_code == 400
    assert "APPROVED or REJECTED" in (res.json().get("detail") or "")


def test_console_demo_key_injection(client, monkeypatch):
    # When DEMO_MODE=true, data-demo-key is injected from the legacy master key
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("AGENT_TRIGGER_API_KEY", "secret-demo-trigger-key")
    res_demo = client.get("/console")
    assert res_demo.status_code == 200
    assert 'data-demo-key="secret-demo-trigger-key"' in res_demo.text
    assert "getAttribute('data-demo-key')" in res_demo.text

    # When DEMO_MODE=false, no data-demo-key attribute
    monkeypatch.setenv("DEMO_MODE", "false")
    res_prod = client.get("/console")
    assert res_prod.status_code == 200
    assert "data-demo-key=" not in res_prod.text


def test_console_injects_manager_key_from_agent_api_keys(client, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.delenv("AGENT_TRIGGER_API_KEY", raising=False)
    monkeypatch.setenv("AGENT_API_KEYS", json.dumps([
        {"key": "inv-only", "scopes": ["trigger:inventory_reorder"]},
        {"key": "manager-demo-key", "scopes": [
            "read:registry", "read:runs", "read:proposals", "resolve:proposals",
            "chat:manager",
        ]},
    ]))
    res = client.get("/console")
    assert res.status_code == 200
    assert 'data-demo-key="manager-demo-key"' in res.text
    assert "inv-only" not in res.text


def test_console_html_field_names_and_neighbourhood_labels(client):
    res = client.get("/console")
    assert res.status_code == 200
    html = res.text

    # Canonical inventory ledger fields
    assert "item_code" in html or "itemCode" in html
    assert "current_stock" in html or "currentStock" in html
    assert "quantity_on_hand" not in html
    assert "reorder_level" not in html

    # Site codes stay in SQL; the manager console shows neighbourhoods
    assert "DOM011" not in html
    assert "PAR011" not in html
    assert "DOM0" not in html
    assert "Oberkampf" in html

    # Corruption guard: key lookup and JS must not be space-punched
    assert "getAttribute('data-demo-key')" in html
    assert "function getApiKey" in html
    assert "data-d      o-key" not in html
    assert "fu      tion" not in html


def test_console_html_agents_rail_paints_from_registry(client):
    """Left rail must replace .team-item nodes from GET /agents envelope."""
    res = client.get("/console")
    assert res.status_code == 200
    html = res.text
    assert "function loadAgentsRail" in html
    assert "data.agents" in html
    # Paint the rail; do not only console.debug the catalog.
    assert "renderAgentRailItem" in html
    assert "host.innerHTML = html" in html
    assert "console.debug('Loaded agents registry:'" not in html
    assert "last_run" in html
    assert ".category" in html or "category" in html
    # Registry failures must be visible; static markup is only degraded UI.
    assert "showRailError('Agent registry failed:" in html
    assert "if (!res.ok) return" not in html
    assert "function updateRailStatuses" in html
    assert "function loadAgentRunsForRail" in html
    assert "function refreshRailStatus" in html
    assert "await refreshRailStatus();" in html
    assert "function neutralRailLabel" in html
    assert "markAgent(agentId, neutralRailLabel(agentId)" in html
    assert "pending proposal" in html


def test_client_approve_via_http_and_demo_tables_flow(seeded_db, monkeypatch, client):
    monkeypatch.setenv("DEMO_DB_PATH", str(seeded_db))
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("AGENT_TRIGGER_API_KEY", "test-key")

    flagship_id = "68a1f2c9e4b0a1234567890a"
    headers = {"X-Agent-Api-Key": "test-key"}

    # 1. Insert a draft PO in demo database
    conn = sqlite3.connect(seeded_db)
    conn.execute(
        "INSERT INTO purchase_orders (id, store_id, supplier_id, status, auto_generated, created_at) VALUES ('PO-FLOW-1', ?, 'sup-1', 'DRAFT', 1, '2026-08-22')",
        (flagship_id,),
    )
    conn.commit()

    # 2. Register pending proposal
    prop = ActionProposal(
        type="DRAFT_PURCHASE_ORDER",
        store_id=flagship_id,
        summary="PO Mozzarella Order",
        rationale="Low stock 6.2 kg",
        agent="inventory_reorder",
        payload={"po_id": "PO-FLOW-1"},
        idempotency_key="idem:po:flow:1",
    )
    saved = proposal_store.save_proposal(prop)
    pid = saved["proposal_id"]

    # 3. Manager approves proposal via HTTP POST
    res_resolve = client.post(
        f"/agent/proposals/{pid}/resolve",
        headers=headers,
        json={"status": "APPROVED", "note": "Approved by manager via console"},
    )
    assert res_resolve.status_code == 200
    res_data = res_resolve.json()
    assert res_data["status"] == "APPROVED"
    assert res_data.get("applied") is True

    # 4. Check demo tables endpoint shows PENDING_APPROVAL
    res_po = client.get(f"/agent/demo/tables/purchase_orders?store_id={flagship_id}", headers=headers)
    assert res_po.status_code == 200
    po_data = res_po.json()
    assert po_data["table"] == "purchase_orders"
    assert po_data["store_code"] == "DOM011"
    matched_pos = [r for r in po_data["rows"] if r["id"] == "PO-FLOW-1"]
    assert len(matched_pos) == 1
    assert matched_pos[0]["status"] == "PENDING_APPROVAL"
    assert matched_pos[0]["approved_by"] == "demo-manager"


def test_client_reject_does_not_advance_po(seeded_db, monkeypatch, client):
    monkeypatch.setenv("DEMO_DB_PATH", str(seeded_db))
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("AGENT_TRIGGER_API_KEY", "test-key")

    flagship_id = "68a1f2c9e4b0a1234567890a"
    headers = {"X-Agent-Api-Key": "test-key"}

    conn = sqlite3.connect(seeded_db)
    orig_menu_price = conn.execute("SELECT price FROM menu_items WHERE id = 'mi_lg_pizza_pepperoni'").fetchone()[0]

    # Insert draft PO
    conn.execute(
        "INSERT INTO purchase_orders (id, store_id, supplier_id, status, auto_generated, created_at) VALUES ('PO-REJ-1', ?, 'sup-1', 'DRAFT', 1, '2026-08-22')",
        (flagship_id,),
    )
    conn.commit()

    prop = ActionProposal(
        type="DRAFT_PURCHASE_ORDER",
        store_id=flagship_id,
        summary="PO Draft to reject",
        rationale="Overstock risk",
        agent="inventory_reorder",
        payload={"po_id": "PO-REJ-1"},
        idempotency_key="idem:po:rej:1",
    )
    saved = proposal_store.save_proposal(prop)
    pid = saved["proposal_id"]

    # Manager rejects proposal
    res = client.post(
        f"/agent/proposals/{pid}/resolve",
        headers=headers,
        json={"status": "REJECTED", "note": "Not needed this week"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "REJECTED"

    # SQLite PO must NOT advance to PENDING_APPROVAL or APPROVED
    row = conn.execute("SELECT status, rejection_reason FROM purchase_orders WHERE id = 'PO-REJ-1'").fetchone()
    assert row[0] == "CANCELLED"
    assert "Not needed" in row[1]

    # Menu price must remain identical
    current_price = conn.execute("SELECT price FROM menu_items WHERE id = 'mi_lg_pizza_pepperoni'").fetchone()[0]
    assert current_price == orig_menu_price == 1290


def test_closed_loop_inventory_approve_via_http(seeded_db, monkeypatch, client):
    """Seed → trigger inventory → proof numbers → approve → PO advances, price stays."""
    flagship_id = "68a1f2c9e4b0a1234567890a"
    monkeypatch.setenv("DEMO_DB_PATH", str(seeded_db))
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("DEMO_FOCUS_STORE_ID", flagship_id)
    monkeypatch.setenv("OPS_PREFER_LLM", "false")
    monkeypatch.setenv("LLM_API_KEY", "dummy")
    monkeypatch.setenv("AGENT_TRIGGER_API_KEY", "test-key")
    monkeypatch.setenv("AGENT_TOKEN", "test-token")
    headers = {"X-Agent-Api-Key": "test-key"}

    trigger = client.post("/agents/inventory-reorder/trigger", headers=headers)
    assert trigger.status_code == 200
    body = trigger.json()
    assert body.get("pos_drafted", 0) >= 1

    conn = sqlite3.connect(seeded_db)
    draft_count = conn.execute(
        "SELECT COUNT(*) FROM purchase_orders WHERE store_id = ? AND status = 'DRAFT'",
        (flagship_id,),
    ).fetchone()[0]
    assert draft_count >= 1

    inv = client.get(
        f"/agent/demo/tables/inventory?store_id={flagship_id}",
        headers=headers,
    )
    assert inv.status_code == 200
    inv_data = inv.json()
    assert inv_data["store_code"] == "DOM011"
    rows = inv_data["rows"]
    mozz = next(r for r in rows if r["item_code"] == "ING-MOZZ-18")
    tom = next(r for r in rows if r["item_code"] == "ING-TOM-12L")
    assert mozz["current_stock"] == 6.2
    assert tom["current_stock"] == 3.1

    pending = client.get("/agent/proposals?status=PENDING", headers=headers)
    assert pending.status_code == 200
    cards = pending.json()["proposals"]
    inventory_cards = [
        p for p in cards
        if p.get("type") == "DRAFT_PURCHASE_ORDER" and p.get("store_id") == flagship_id
    ]
    assert len(inventory_cards) >= 1
    pid = inventory_cards[0]["proposal_id"]

    resolved = client.post(
        f"/agent/proposals/{pid}/resolve",
        headers=headers,
        json={"status": "APPROVED", "note": "closed-loop smoke"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "APPROVED"
    assert resolved.json().get("applied") is True

    po = client.get(
        f"/agent/demo/tables/purchase_orders?store_id={flagship_id}",
        headers=headers,
    )
    assert po.status_code == 200
    po_rows = po.json()["rows"]
    assert any(r["status"] == "PENDING_APPROVAL" for r in po_rows)

    price = conn.execute(
        "SELECT price FROM menu_items WHERE id = 'mi_lg_pizza_pepperoni'"
    ).fetchone()[0]
    assert price == 1290

    agents = client.get("/agents", headers=headers)
    assert agents.status_code == 200
    catalog = agents.json()
    assert isinstance(catalog, dict)
    assert len(catalog["agents"]) == 9
    assert "manager_chat" in {a["id"] for a in catalog["agents"]}

    runs = client.get(f"/agent/runs?storeId={flagship_id}", headers=headers)
    assert runs.status_code == 200
    assert "runs" in runs.json()
