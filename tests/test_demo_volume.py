"""CI volume gates for data/demo/masova_demo.sqlite when present."""

import sqlite3
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEMO_DB_PATH = PROJECT_ROOT / "data" / "demo" / "masova_demo.sqlite"

# Order-count bands aligned with seed_demo_data LARGE / MEDIUM / SMALL (~90 days).
_LARGE_MIN = 2400
_MEDIUM_MIN = 1400


def _order_count_band(count: int) -> str:
    if count >= _LARGE_MIN:
        return "large"
    if count >= _MEDIUM_MIN:
        return "medium"
    return "small"


@pytest.mark.skipif(not DEMO_DB_PATH.exists(), reason="no demo db")
def test_paris_fleet_volume_bands():
    conn = sqlite3.connect(DEMO_DB_PATH)
    try:
        store_count = conn.execute("SELECT COUNT(*) FROM stores").fetchone()[0]
        assert store_count == 24

        order_count = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        assert order_count >= 45000

        inventory_count = conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
        assert inventory_count == 1152

        per_store = conn.execute(
            "SELECT store_id, COUNT(*) FROM orders GROUP BY store_id"
        ).fetchall()
        assert len(per_store) == 24

        bands = {_order_count_band(count) for _, count in per_store}
        assert len(bands) >= 3, f"Expected >=3 order-volume bands, got {sorted(bands)}"
    finally:
        conn.close()
