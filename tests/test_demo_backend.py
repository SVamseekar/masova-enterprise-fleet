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
