import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    db_file = tmp_path / "masova_demo.sqlite"
    from scripts.seed_demo_data import seed
    seed(str(db_file))
    monkeypatch.setenv("DEMO_DB_PATH", str(db_file))
    monkeypatch.setenv("DEMO_MODE", "true")
    return str(db_file)


def test_approve_price_suggestion_writes_capped_menu_price(seeded_db, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    from masova_agent.runtime.proposal_apply import apply_approved_proposal
    from masova_agent.services.demo_backend import _connect
    conn = _connect()
    row = conn.execute("SELECT id, price FROM menu_items LIMIT 1").fetchone()
    before = row["price"]
    ok = apply_approved_proposal({
        "type": "SUGGEST_PRICE_ADJUSTMENT",
        "store_id": "any",
        "payload": {"item_ids": [row["id"]], "percent": 10, "direction": "increase"},
    })
    assert ok is True
    after = conn.execute("SELECT price FROM menu_items WHERE id=?", (row["id"],)).fetchone()["price"]
    assert after != before


def test_approve_price_caps_increase_at_12_percent(seeded_db, monkeypatch):
    from masova_agent.runtime.proposal_apply import apply_approved_proposal
    from masova_agent.services.demo_backend import _connect
    conn = _connect()
    row = conn.execute("SELECT id, price FROM menu_items LIMIT 1").fetchone()
    before = float(row["price"])
    apply_approved_proposal({
        "type": "SUGGEST_PRICE_ADJUSTMENT",
        "store_id": "any",
        "payload": {"item_ids": [row["id"]], "percent": 50, "direction": "increase"},
    })
    after = float(conn.execute("SELECT price FROM menu_items WHERE id=?", (row["id"],)).fetchone()["price"])
    expected = round(before * (1 + 12 / 100), 2)
    assert after == expected


def test_reject_price_suggestion_never_writes_prices(seeded_db, monkeypatch):
    from masova_agent.runtime.proposal_apply import apply_rejected_proposal
    from masova_agent.services.demo_backend import _connect
    conn = _connect()
    row = conn.execute("SELECT id, price FROM menu_items LIMIT 1").fetchone()
    before = row["price"]
    apply_rejected_proposal({
        "type": "SUGGEST_PRICE_ADJUSTMENT",
        "store_id": "any",
        "payload": {"item_ids": [row["id"]], "percent": 10, "direction": "increase"},
    })
    after = conn.execute("SELECT price FROM menu_items WHERE id=?", (row["id"],)).fetchone()["price"]
    assert after == before


def test_approve_po_does_not_mutate_another_store(seeded_db, monkeypatch):
    from masova_agent.runtime.proposal_apply import apply_approved_proposal
    from masova_agent.services.demo_backend import _connect

    conn = _connect()
    a = conn.execute("SELECT id FROM stores ORDER BY code LIMIT 1").fetchone()["id"]
    b = conn.execute("SELECT id FROM stores ORDER BY code LIMIT 1 OFFSET 1").fetchone()["id"]
    conn.execute(
        "INSERT INTO purchase_orders (id, store_id, supplier_id, status, auto_generated, created_at) "
        "VALUES ('PO-A', ?, 'sup', 'DRAFT', 1, 't'), ('PO-B', ?, 'sup', 'DRAFT', 1, 't')",
        (a, b),
    )
    conn.commit()
    ok = apply_approved_proposal({
        "type": "DRAFT_PURCHASE_ORDER",
        "store_id": a,
        "payload": {"po_id": "PO-B"},
    })
    assert ok is True
    statuses = {
        row["id"]: row["status"]
        for row in conn.execute("SELECT id, status FROM purchase_orders WHERE id IN ('PO-A','PO-B')")
    }
    assert statuses["PO-B"] == "DRAFT"
    assert statuses["PO-A"] == "DRAFT"


def test_approve_shifts_without_store_id_does_not_confirm_fleet(seeded_db, monkeypatch):
    from masova_agent.runtime.proposal_apply import apply_approved_proposal
    from masova_agent.services.demo_backend import _connect

    conn = _connect()
    store = conn.execute("SELECT id FROM stores LIMIT 1").fetchone()["id"]
    staff = conn.execute("SELECT id, name, role FROM staff WHERE store_id = ? LIMIT 1", (store,)).fetchone()
    conn.execute(
        "INSERT INTO staff_shifts (id, store_id, staff_id, staff_name, role, date, start_time, end_time, status) "
        "VALUES ('SH-ISO', ?, ?, ?, ?, '2026-09-01', '09:00', '17:00', 'DRAFT')",
        (store, staff["id"], staff["name"], staff["role"]),
    )
    conn.commit()
    ok = apply_approved_proposal({
        "type": "DRAFT_SHIFT_ROSTER",
        "store_id": "",
        "payload": {},
    })
    assert ok is False
    status = conn.execute("SELECT status FROM staff_shifts WHERE id = 'SH-ISO'").fetchone()["status"]
    assert status == "DRAFT"


def test_approve_forecast_inserts_manager_action(seeded_db, monkeypatch):
    from masova_agent.runtime.proposal_apply import apply_approved_proposal
    from masova_agent.services.demo_backend import _connect
    ok = apply_approved_proposal({
        "type": "WRITE_FORECAST",
        "store_id": "s1",
        "payload": {"horizon": 7},
    })
    assert ok is True
    conn = _connect()
    row = conn.execute(
        "SELECT type, status FROM manager_actions WHERE store_id = ?",
        ("s1",),
    ).fetchone()
    assert row is not None
    assert row["type"] == "WRITE_FORECAST"
