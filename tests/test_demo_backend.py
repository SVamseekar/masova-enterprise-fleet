"""
Tests for Demo Data Layer (Phase 5).

Asserts synthetic Paris fleet scale (24 stores, 3 size bands, ~50k orders,
canonical field shapes, hero inventory on flagship only, calendar tags, etc.).
"""

import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from fixtures.backend_contracts import ORDER_STATUSES_CANONICAL, PO_STATUSES

FLAGSHIP_STORE_ID = "68a1f2c9e4b0a1234567890a"
FLAGSHIP_STORE_CODE = "DOM011"


@pytest.fixture(scope="module")
def seeded_db(tmp_path_factory):
    db_dir = tmp_path_factory.mktemp("demo_data")
    db_path = db_dir / "masova_demo.sqlite"
    os.environ["DEMO_DB_PATH"] = str(db_path)
    import scripts.seed_demo_data as seed_mod
    seed_mod.seed(str(db_path))
    return str(db_path)


def test_seed_creates_24_paris_stores(seeded_db):
    conn = sqlite3.connect(seeded_db)
    stores = conn.execute("SELECT id, code, name, city, currency, country_code, locale, status FROM stores").fetchall()
    assert len(stores) == 24

    # Flagship check
    flagship = [s for s in stores if s[0] == FLAGSHIP_STORE_ID]
    assert len(flagship) == 1
    f = flagship[0]
    assert f[1] == "DOM011"
    assert "Oberkampf" in f[2]
    assert f[3] == "Paris"
    assert f[4] == "EUR"
    assert f[5] == "FR"
    assert f[6] == "fr-FR"
    assert f[7] == "ACTIVE"

    # All stores must have distinct ObjectIds
    ids = {s[0] for s in stores}
    assert len(ids) == 24
    assert all(len(sid) == 24 for sid in ids)
    assert all(s[1].startswith("DOM") for s in stores)


def test_seed_creates_distinct_volume_clusters(seeded_db):
    conn = sqlite3.connect(seeded_db)
    rows = conn.execute("SELECT store_id, COUNT(*) FROM orders GROUP BY store_id").fetchall()
    assert len(rows) == 24

    counts = [r[1] for r in rows]
    large_cluster = [c for c in counts if c >= 2400]
    medium_cluster = [c for c in counts if 1400 <= c < 2400]
    small_cluster = [c for c in counts if c < 1400]

    assert len(large_cluster) == 6, f"Expected 6 large stores, got {len(large_cluster)}"
    assert len(medium_cluster) == 12, f"Expected 12 medium stores, got {len(medium_cluster)}"
    assert len(small_cluster) == 6, f"Expected 6 small stores, got {len(small_cluster)}"


def test_seed_total_orders_and_items_volumes(seeded_db):
    conn = sqlite3.connect(seeded_db)
    total_orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    assert total_orders >= 20000
    assert 35000 <= total_orders <= 65000

    total_order_items = conn.execute("SELECT COUNT(*) FROM order_items").fetchone()[0]
    ratio = total_order_items / total_orders
    assert 2.0 <= ratio <= 3.5  # ~2.8x order lines per order


def test_seed_hero_inventory_on_flagship_only(seeded_db):
    conn = sqlite3.connect(seeded_db)
    
    # Total inventory rows = 24 stores x 48 SKUs = 1152
    total_inv = conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
    assert total_inv == 1152

    # Hero store low stock check
    hero_low = conn.execute(
        "SELECT item_code, item_name, current_stock, minimum_stock, unit FROM inventory WHERE store_id = ? AND current_stock < minimum_stock",
        (FLAGSHIP_STORE_ID,),
    ).fetchall()
    
    assert len(hero_low) == 2
    low_codes = {r[0] for r in hero_low}
    assert low_codes == {"ING-MOZZ-18", "ING-TOM-12L"}

    mozz = [r for r in hero_low if r[0] == "ING-MOZZ-18"][0]
    assert mozz[2] == 6.2
    assert mozz[3] == 10.0
    assert mozz[4] == "kg"

    tom = [r for r in hero_low if r[0] == "ING-TOM-12L"][0]
    assert tom[2] == 3.1
    assert tom[3] == 6.0
    assert tom[4] == "L"


def test_seed_calendar_has_90_days_and_all_required_tags(seeded_db):
    conn = sqlite3.connect(seeded_db)
    rows = conn.execute("SELECT date, tags_json FROM calendar").fetchall()
    assert len(rows) == 90

    all_tags = set()
    for _, tags_json in rows:
        import json
        tags = json.loads(tags_json)
        all_tags.update(tags)

    required_tags = {
        "weekday_dip",
        "weekend_peak",
        "rain",
        "heatwave",
        "holiday_quiet",
        "holiday_peak",
        "event",
        "dry",
    }
    assert required_tags.issubset(all_tags), f"Missing tags: {required_tags - all_tags}"


def test_seed_customers_and_gdpr_marketing_opt_in(seeded_db):
    conn = sqlite3.connect(seeded_db)
    total_customers = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
    assert total_customers >= 25000

    # Check marketing consent default false (majority false)
    opt_in_count = conn.execute("SELECT COUNT(*) FROM customers WHERE marketing_consent = 1").fetchone()[0]
    assert opt_in_count < total_customers * 0.4  # majority have marketingOptIn false


def test_seed_staff_and_shifts(seeded_db):
    conn = sqlite3.connect(seeded_db)
    total_staff = conn.execute("SELECT COUNT(*) FROM staff").fetchone()[0]
    assert 400 <= total_staff <= 550

    total_shifts = conn.execute("SELECT COUNT(*) FROM staff_shifts").fetchone()[0]
    assert 5000 <= total_shifts <= 8000


def test_seed_reviews_volume(seeded_db):
    conn = sqlite3.connect(seeded_db)
    total_reviews = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
    assert 800 <= total_reviews <= 2000


def test_seed_orders_use_canonical_statuses(seeded_db):
    conn = sqlite3.connect(seeded_db)
    statuses = {r[0] for r in conn.execute("SELECT DISTINCT status FROM orders").fetchall()}
    assert statuses.issubset(ORDER_STATUSES_CANONICAL)


def test_seed_menu_items_minor_units(seeded_db):
    conn = sqlite3.connect(seeded_db)
    prices = [r[0] for r in conn.execute("SELECT price FROM menu_items").fetchall()]
    assert len(prices) > 0
    assert all(isinstance(p, int) and p > 100 for p in prices)


def test_demo_backend_get_stores_spring_page(seeded_db, monkeypatch):
    monkeypatch.setenv("DEMO_DB_PATH", str(seeded_db))
    monkeypatch.setenv("DEMO_MODE", "true")
    from masova_agent.services import demo_backend

    res = demo_backend.get("/api/stores", None)
    assert "content" in res
    assert len(res["content"]) == 24
    flagship = [s for s in res["content"] if s["id"] == FLAGSHIP_STORE_ID][0]
    assert flagship["code"] == FLAGSHIP_STORE_CODE
    assert flagship["operatingConfig"]["openingTime"] == "09:00"
    assert flagship["operatingConfig"]["isOpen"] is True


def test_demo_backend_get_store_by_id(seeded_db, monkeypatch):
    monkeypatch.setenv("DEMO_DB_PATH", str(seeded_db))
    monkeypatch.setenv("DEMO_MODE", "true")
    from masova_agent.services import demo_backend

    res = demo_backend.get(f"/stores/{FLAGSHIP_STORE_ID}", None)
    assert res["id"] == FLAGSHIP_STORE_ID
    assert res["code"] == FLAGSHIP_STORE_CODE
    assert res["currency"] == "EUR"


def test_demo_backend_get_menu(seeded_db, monkeypatch):
    monkeypatch.setenv("DEMO_DB_PATH", str(seeded_db))
    monkeypatch.setenv("DEMO_MODE", "true")
    from masova_agent.services import demo_backend

    res = demo_backend.get("/menu", {"storeId": FLAGSHIP_STORE_ID})
    assert "content" in res
    assert len(res["content"]) == 48
    pepperoni = [m for m in res["content"] if m["id"] == "mi_lg_pizza_pepperoni"][0]
    assert pepperoni["basePrice"] == 1290
    assert pepperoni["available"] is True


def test_demo_backend_get_orders_and_order_by_id(seeded_db, monkeypatch):
    monkeypatch.setenv("DEMO_DB_PATH", str(seeded_db))
    monkeypatch.setenv("DEMO_MODE", "true")
    from masova_agent.services import demo_backend

    orders = demo_backend.get("/orders", {"storeId": FLAGSHIP_STORE_ID, "size": 5})
    assert "content" in orders
    assert len(orders["content"]) > 0

    first_order_id = orders["content"][0]["id"]
    single_order = demo_backend.get(f"/orders/{first_order_id}", None)
    assert single_order["id"] == first_order_id
    assert "status" in single_order
    assert len(single_order.get("items", [])) > 0


def test_demo_backend_get_customer_by_id(seeded_db, monkeypatch):
    monkeypatch.setenv("DEMO_DB_PATH", str(seeded_db))
    monkeypatch.setenv("DEMO_MODE", "true")
    from masova_agent.services import demo_backend

    res = demo_backend.get("/customers/CUST000001", None)
    assert res["id"] == "CUST000001"
    assert "loyaltyInfo" in res
    assert "orderStats" in res
    assert "points" in res["loyaltyInfo"]
    assert "tier" in res["loyaltyInfo"]


def test_demo_backend_post_purchase_order_inserts_draft_row(seeded_db, monkeypatch):
    monkeypatch.setenv("DEMO_DB_PATH", str(seeded_db))
    monkeypatch.setenv("DEMO_MODE", "true")
    from masova_agent.services import demo_backend

    payload = {
        "storeId": FLAGSHIP_STORE_ID,
        "supplierId": "sup_dairy_pt_04",
        "items": [
            {"itemName": "Mozzarella (kg)", "quantity": 18, "unitCost": 5.2},
            {"itemName": "Tomato Base (L)", "quantity": 12, "unitCost": 3.8},
        ],
        "notes": "Low stock reorder",
    }
    res = demo_backend.post("/api/purchase-orders/auto-generate", payload)
    assert res["status"] == "DRAFT"
    po_id = res["id"]

    conn = sqlite3.connect(seeded_db)
    row = conn.execute("SELECT status, store_id, supplier_id FROM purchase_orders WHERE id = ?", (po_id,)).fetchone()
    assert row is not None
    assert row[0] == "DRAFT"
    assert row[1] == FLAGSHIP_STORE_ID
    assert row[2] == "sup_dairy_pt_04"

    item_rows = conn.execute("SELECT item_name, quantity FROM purchase_order_items WHERE purchase_order_id = ?", (po_id,)).fetchall()
    assert len(item_rows) == 2


def test_demo_backend_missing_sqlite_fails_loudly(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_DB_PATH", str(tmp_path / "non_existent.sqlite"))
    monkeypatch.setenv("DEMO_MODE", "true")
    from masova_agent.services import demo_backend

    with pytest.raises(RuntimeError, match="seed_demo_data"):
        demo_backend.get("/api/stores", None)


def test_ops_http_get_json_uses_demo_backend_when_demo_mode(seeded_db, monkeypatch):
    monkeypatch.setenv("DEMO_DB_PATH", str(seeded_db))
    monkeypatch.setenv("DEMO_MODE", "true")
    import asyncio
    import httpx
    from masova_agent.tools.ops_http import get_json

    async def _run():
        async with httpx.AsyncClient() as client:
            return await get_json(client, "/api/stores")

    status, body = asyncio.run(_run())
    assert status == 200
    assert "content" in body
    assert len(body["content"]) == 24


def test_backend_tools_get_uses_demo_backend_when_demo_mode(seeded_db, monkeypatch):
    monkeypatch.setenv("DEMO_DB_PATH", str(seeded_db))
    monkeypatch.setenv("DEMO_MODE", "true")
    from masova_agent.tools import backend_tools

    body = backend_tools._get(f"/stores/{FLAGSHIP_STORE_ID}")
    assert body["id"] == FLAGSHIP_STORE_ID
    assert body["code"] == FLAGSHIP_STORE_CODE


@pytest.mark.asyncio
async def test_ops_tools_list_low_stock_and_draft_po(seeded_db, monkeypatch):
    monkeypatch.setenv("DEMO_DB_PATH", str(seeded_db))
    monkeypatch.setenv("DEMO_MODE", "true")
    from masova_agent.tools import ops_tools

    low_res = await ops_tools.list_low_stock(FLAGSHIP_STORE_ID)
    assert low_res["ok"] is True
    assert low_res["count"] == 2
    item_names = {i["item_name"] for i in low_res["items"]}
    assert "Mozzarella (kg)" in item_names
    assert "Tomato Base (L)" in item_names

    po_res = await ops_tools.create_draft_po(
        store_id=FLAGSHIP_STORE_ID,
        supplier_id="sup_dairy_pt_04",
        items=[{"itemName": "Mozzarella (kg)", "quantity": 18, "unitCost": 5.2}],
        notes="Automated draft PO",
    )
    assert po_res["ok"] is True
    assert po_res["proposal"]["type"] == "DRAFT_PURCHASE_ORDER"
    assert po_res["proposal"]["requires_approval"] is True


@pytest.mark.asyncio
async def test_ops_tools_churn_and_campaign(seeded_db, monkeypatch):
    monkeypatch.setenv("DEMO_DB_PATH", str(seeded_db))
    monkeypatch.setenv("DEMO_MODE", "true")
    from masova_agent.tools import ops_tools

    churn_res = await ops_tools.read_churn_segment(FLAGSHIP_STORE_ID)
    assert churn_res["ok"] is True
    assert "customers" in churn_res

    camp_res = await ops_tools.create_draft_campaign(
        store_id=FLAGSHIP_STORE_ID,
        customer_ids=["CUST000001", "CUST000002"],
        name="Win Back Summer",
        discount_percent=15.0,
        message="Come back for 15% off!",
    )
    assert camp_res["ok"] is True
    assert camp_res["proposal"]["type"] == "DRAFT_CHURN_CAMPAIGN"


@pytest.mark.asyncio
async def test_ops_tools_roster_and_shifts(seeded_db, monkeypatch):
    monkeypatch.setenv("DEMO_DB_PATH", str(seeded_db))
    monkeypatch.setenv("DEMO_MODE", "true")
    from masova_agent.tools import ops_tools

    staff_res = await ops_tools.read_staff_slots(FLAGSHIP_STORE_ID)
    assert staff_res["ok"] is True
    assert len(staff_res["staff"]) >= 10

    draft_shifts = await ops_tools.create_draft_shifts(
        store_id=FLAGSHIP_STORE_ID,
        shifts=[
            {
                "userId": staff_res["staff"][0].get("id", "staff-1"),
                "name": staff_res["staff"][0].get("name", "Staff Member"),
                "role": "KITCHEN_STAFF",
                "date": "2026-08-25",
                "startTime": "09:00",
                "endTime": "17:00",
            }
        ],
    )
    assert draft_shifts["ok"] is True
    assert draft_shifts["proposal"]["type"] == "DRAFT_SHIFT_ROSTER"


@pytest.mark.asyncio
async def test_ops_tools_forecast_and_kitchen(seeded_db, monkeypatch):
    monkeypatch.setenv("DEMO_DB_PATH", str(seeded_db))
    monkeypatch.setenv("DEMO_MODE", "true")
    from masova_agent.tools import ops_tools

    forecast = await ops_tools.get_forecast_snippet(FLAGSHIP_STORE_ID)
    assert forecast["ok"] is True
    assert "forecasts" in forecast

    kitchen = await ops_tools.read_kitchen_metrics(FLAGSHIP_STORE_ID)
    assert kitchen["ok"] is True
    assert "avg_prep_minutes" in kitchen


@pytest.mark.asyncio
async def test_ops_tools_list_stores(seeded_db, monkeypatch):
    monkeypatch.setenv("DEMO_DB_PATH", str(seeded_db))
    monkeypatch.setenv("DEMO_MODE", "true")
    from masova_agent.tools import ops_tools

    stores_res = await ops_tools.list_stores()
    assert stores_res["ok"] is True
    assert len(stores_res["stores"]) == 24


@pytest.mark.asyncio
async def test_golden_path_inventory_reorder_demo_mode(seeded_db, monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_DB_PATH", str(seeded_db))
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("DEMO_FOCUS_STORE_ID", FLAGSHIP_STORE_ID)
    monkeypatch.setenv("OPS_PREFER_LLM", "false")
    monkeypatch.setenv("PROPOSAL_DATA_DIR", str(tmp_path / "proposals"))

    from masova_agent.agents.inventory_reorder_agent import run_inventory_reorder
    from masova_agent.runtime import proposal_store

    # 1. Execute agent run
    result = await run_inventory_reorder()
    assert result.get("status") == "ok"
    assert result.get("pos_drafted", 0) >= 1

    # 2. Inspect real SQLite database for inserted draft PO on flagship
    conn = sqlite3.connect(seeded_db)
    po_rows = conn.execute(
        "SELECT id, store_id, supplier_id, status FROM purchase_orders WHERE store_id = ? AND status = 'DRAFT'",
        (FLAGSHIP_STORE_ID,),
    ).fetchall()
    assert len(po_rows) >= 1, "Expected at least 1 DRAFT purchase order inserted in SQLite on flagship"

    po_id = po_rows[0][0]
    item_rows = conn.execute(
        "SELECT item_name, quantity FROM purchase_order_items WHERE purchase_order_id = ?",
        (po_id,),
    ).fetchall()
    assert len(item_rows) >= 1
    item_names = {r[0] for r in item_rows}
    assert any("Mozzarella" in name or "Tomato" in name for name in item_names)

    # 3. Verify ProposalStore has registered the proposal with status PENDING
    proposals = proposal_store.list_proposals(store_id=FLAGSHIP_STORE_ID)
    assert len(proposals) >= 1
    po_props = [p for p in proposals if p["type"] == "DRAFT_PURCHASE_ORDER"]
    assert len(po_props) >= 1
    assert po_props[0]["status"] == "PENDING"
    assert po_props[0]["store_id"] == FLAGSHIP_STORE_ID


def test_proposal_apply_approved_po(seeded_db, monkeypatch):
    monkeypatch.setenv("DEMO_DB_PATH", str(seeded_db))
    monkeypatch.setenv("DEMO_MODE", "true")
    from masova_agent.runtime import proposal_apply

    conn = sqlite3.connect(seeded_db)
    # Insert a test draft PO
    conn.execute(
        "INSERT INTO purchase_orders (id, store_id, supplier_id, status, auto_generated, created_at) VALUES ('PO-TEST-1', ?, 'sup-1', 'DRAFT', 1, '2026-08-22')",
        (FLAGSHIP_STORE_ID,),
    )
    conn.commit()

    proposal = {
        "proposal_id": "prop-123",
        "type": "DRAFT_PURCHASE_ORDER",
        "store_id": FLAGSHIP_STORE_ID,
        "payload": {"po_id": "PO-TEST-1"},
    }
    applied = proposal_apply.apply_approved_proposal(proposal)
    assert applied is True

    row = conn.execute("SELECT status, approved_by FROM purchase_orders WHERE id = 'PO-TEST-1'").fetchone()
    assert row[0] in ("PENDING_APPROVAL", "APPROVED")
    assert row[1] == "demo-manager"


def test_proposal_apply_suggest_price_never_mutates_menu_price(seeded_db, monkeypatch):
    monkeypatch.setenv("DEMO_DB_PATH", str(seeded_db))
    monkeypatch.setenv("DEMO_MODE", "true")
    from masova_agent.runtime import proposal_apply

    conn = sqlite3.connect(seeded_db)
    orig_price = conn.execute("SELECT price FROM menu_items WHERE id = 'mi_lg_pizza_pepperoni'").fetchone()[0]

    proposal = {
        "proposal_id": "prop-456",
        "type": "SUGGEST_PRICE_ADJUSTMENT",
        "store_id": FLAGSHIP_STORE_ID,
        "payload": {"item_ids": ["mi_lg_pizza_pepperoni"], "direction": "increase", "percent": 12.0},
    }
    applied = proposal_apply.apply_approved_proposal(proposal)
    assert applied is False or applied is True

    # Critical invariant: menu item price must NEVER change
    new_price = conn.execute("SELECT price FROM menu_items WHERE id = 'mi_lg_pizza_pepperoni'").fetchone()[0]
    assert new_price == orig_price


def test_demo_tables_endpoint(seeded_db, monkeypatch):
    monkeypatch.setenv("DEMO_DB_PATH", str(seeded_db))
    monkeypatch.setenv("DEMO_MODE", "true")
    from fastapi.testclient import TestClient
    from masova_agent.main import app

    client = TestClient(app)
    
    # 1. Allowed table
    res = client.get("/agent/demo/tables/stores")
    assert res.status_code == 200
    data = res.json()
    assert data["table"] == "stores"
    assert data["total"] == 24
    assert len(data["rows"]) == 24

    # 2. Filter by store_id
    res_inv = client.get(f"/agent/demo/tables/inventory?store_id={FLAGSHIP_STORE_ID}")
    assert res_inv.status_code == 200
    data_inv = res_inv.json()
    assert data_inv["total"] == 48

    # 3. Disallowed table returns 400
    res_disallowed = client.get("/agent/demo/tables/non_existent_or_secret")
    assert res_disallowed.status_code == 400
    detail = res_disallowed.json().get("detail") or res_disallowed.json().get("error", "")
    assert "not in allowlist" in detail







