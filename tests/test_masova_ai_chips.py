"""
Chip → API integration tests (MaSoVa AI console golden path).

Asserts inventory chip trigger grounds proposals in demo SQL inventory for the
focus store — not invented UI numbers.
"""

from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from masova_agent.main import app
from masova_agent.runtime import proposal_store

FOCUS_STORE_ID = "68a1f2c9e4b0a1234567890a"
TRIGGER_HEADERS = {"X-Agent-Api-Key": "test-key"}


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


@pytest.fixture
def demo_env(seeded_db, monkeypatch):
    """DEMO_MODE + focus store + rule fallback (no LLM)."""
    monkeypatch.setenv("DEMO_DB_PATH", str(seeded_db))
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("DEMO_FOCUS_STORE_ID", FOCUS_STORE_ID)
    monkeypatch.setenv("OPS_PREFER_LLM", "false")
    monkeypatch.setenv("LLM_API_KEY", "dummy")
    monkeypatch.setenv("AGENT_TRIGGER_API_KEY", "test-key")
    monkeypatch.setenv("AGENT_TOKEN", "test-token")
    from masova_agent.runtime.idempotency import clear_for_tests

    clear_for_tests()
    return seeded_db


def _low_stock_inventory(client, store_id: str) -> list[dict]:
    res = client.get(
        f"/agent/demo/tables/inventory?store_id={store_id}",
        headers=TRIGGER_HEADERS,
    )
    assert res.status_code == 200
    rows = res.json()["rows"]
    return [r for r in rows if r["current_stock"] < r["minimum_stock"]]


def _proposal_blob(proposal: dict) -> str:
    return json.dumps(
        {
            "summary": proposal.get("summary"),
            "rationale": proposal.get("rationale"),
            "payload": proposal.get("payload"),
        }
    )


def test_inventory_trigger_creates_run_and_proposal(client, demo_env):
    """POST /agents/inventory-reorder/trigger → run + grounded DRAFT_PURCHASE_ORDER."""
    low_stock = _low_stock_inventory(client, FOCUS_STORE_ID)
    assert len(low_stock) >= 2, "seed must expose hero low-stock rows on flagship"
    stock_by_code = {r["item_code"]: r for r in low_stock}
    assert stock_by_code["ING-MOZZ-18"]["current_stock"] == 6.2
    assert stock_by_code["ING-TOM-12L"]["current_stock"] == 3.1

    trigger = client.post(
        "/agents/inventory-reorder/trigger",
        headers=TRIGGER_HEADERS,
    )
    assert trigger.status_code == 200
    body = trigger.json()
    assert body.get("status") == "ok"
    assert body.get("pos_drafted", 0) >= 1

    runtime = body.get("_runtime") or {}
    run_id = runtime.get("run_id") or body.get("run_id")
    assert run_id, "trigger response must include run_id (top-level or _runtime)"

    conn = sqlite3.connect(demo_env)
    draft_count = conn.execute(
        "SELECT COUNT(*) FROM purchase_orders WHERE store_id = ? AND status = 'DRAFT'",
        (FOCUS_STORE_ID,),
    ).fetchone()[0]
    assert draft_count >= 1

    pending = client.get(
        f"/agent/proposals?status=PENDING&type=DRAFT_PURCHASE_ORDER&storeId={FOCUS_STORE_ID}",
        headers=TRIGGER_HEADERS,
    )
    assert pending.status_code == 200
    proposals = pending.json()["proposals"]
    focus_po = [p for p in proposals if p.get("store_id") == FOCUS_STORE_ID]
    assert len(focus_po) >= 1
    proposal_evidence = [
        evidence
        for prop in focus_po
        for evidence in (prop.get("evidence") or [])
    ]
    assert any(
        evidence == {
            "tool": "list_low_stock",
            "row_id": stock_by_code["ING-MOZZ-18"]["id"],
            "field": "currentStock",
            "value": 6.2,
        }
        for evidence in proposal_evidence
    )

    inv_ids = {r["id"] for r in low_stock}
    inv_names = {r["item_name"] for r in low_stock}
    reorder_qtys = {r["reorder_quantity"] for r in low_stock}
    stock_values = {str(r["current_stock"]) for r in low_stock}

    grounded = False
    for prop in focus_po:
        blob = _proposal_blob(prop)
        if any(val in blob for val in stock_values):
            grounded = True

        payload = prop.get("payload") or {}
        line_items = payload.get("items") or []
        for line in line_items:
            inv_id = line.get("inventoryItemId") or line.get("inventory_item_id")
            if inv_id and inv_id in inv_ids:
                grounded = True
            name = line.get("itemName") or line.get("item_name") or ""
            if name and any(n in name or name in n for n in inv_names):
                grounded = True
            qty = line.get("quantity")
            if qty is not None and qty in reorder_qtys:
                grounded = True

    assert grounded, (
        "proposal payload/text must reference focus-store low-stock inventory "
        f"(stock values {sorted(stock_values)}, reorder qtys {sorted(reorder_qtys)})"
    )
