"""Each focused store must only see and mutate its own rows."""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from masova_agent.main import app
from masova_agent.runtime import proposal_store, run_store

FLAGSHIP_ID = "68a1f2c9e4b0a1234567890a"
OTHER_ID = "68a1f2c9e4b0a12345678914"  # Belleville / DOM020
BASTILLE_ID = "68a1f2c9e4b0a12345678904"
HEADERS = {"X-Agent-Api-Key": "test-key"}
KITCHEN_STATUSES = ("RECEIVED", "PREPARING", "OVEN", "BAKED", "READY")

OPS_TRIGGERS = [
    ("demand_forecast", "/agents/demand-forecast/trigger"),
    ("inventory_reorder", "/agents/inventory-reorder/trigger"),
    ("churn_prevention", "/agents/churn-prevention/trigger"),
    ("review_response", "/agents/review-response/trigger"),
    ("shift_optimisation", "/agents/shift-optimisation/trigger"),
    ("kitchen_coach", "/agents/kitchen-coach/trigger"),
    ("dynamic_pricing", "/agents/dynamic-pricing/trigger"),
]


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def seeded_db(tmp_path):
    db_file = tmp_path / "masova_demo.sqlite"
    from scripts.seed_demo_data import seed

    seed(str(db_file))
    return str(db_file)


@pytest.fixture
def demo_env(seeded_db, tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_DB_PATH", str(seeded_db))
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("DEMO_FOCUS_STORE_ID", FLAGSHIP_ID)
    monkeypatch.setenv("OPS_PREFER_LLM", "false")
    monkeypatch.setenv("LLM_API_KEY", "dummy")
    monkeypatch.setenv("AGENT_TRIGGER_API_KEY", "test-key")
    monkeypatch.setenv("AGENT_TOKEN", "test-token")
    monkeypatch.setenv("PROPOSAL_DATA_DIR", str(tmp_path / "proposals"))
    monkeypatch.setenv("RUN_DATA_DIR", str(tmp_path / "runs"))
    monkeypatch.delenv("AGENT_API_KEYS", raising=False)
    proposal_store.clear_for_tests()
    run_store.clear_for_tests()
    yield seeded_db
    proposal_store.clear_for_tests()
    run_store.clear_for_tests()


def test_inventory_rows_never_cross_stores(client, demo_env):
    flag = client.get(f"/agent/demo/tables/inventory?store_id={FLAGSHIP_ID}", headers=HEADERS)
    other = client.get(f"/agent/demo/tables/inventory?store_id={OTHER_ID}", headers=HEADERS)
    assert flag.status_code == 200
    assert other.status_code == 200
    flag_rows = flag.json()["rows"]
    other_rows = other.json()["rows"]
    assert flag_rows
    assert other_rows
    assert {r["store_id"] for r in flag_rows} == {FLAGSHIP_ID}
    assert {r["store_id"] for r in other_rows} == {OTHER_ID}
    flag_ids = {r["id"] for r in flag_rows}
    other_ids = {r["id"] for r in other_rows}
    assert flag_ids.isdisjoint(other_ids)


def test_customers_table_scopes_to_primary_store(client, demo_env):
    res = client.get(
        f"/agent/demo/tables/customers?store_id={OTHER_ID}&limit=50",
        headers=HEADERS,
    )
    assert res.status_code == 200
    rows = res.json()["rows"]
    assert rows
    assert all(r.get("primary_store_id") == OTHER_ID for r in rows)


def test_inventory_trigger_other_store_does_not_write_flagship_proposals(client, demo_env):
    res = client.post(
        "/agents/inventory-reorder/trigger",
        headers=HEADERS,
        json={"storeId": OTHER_ID},
    )
    assert res.status_code == 200
    body = res.json()
    for p in body.get("proposals") or []:
        assert p.get("store_id") == OTHER_ID

    listed = client.get(
        f"/agent/proposals?storeId={OTHER_ID}",
        headers=HEADERS,
    ).json()["proposals"]
    assert all(p["store_id"] == OTHER_ID for p in listed)

    flag_listed = client.get(
        f"/agent/proposals?storeId={FLAGSHIP_ID}",
        headers=HEADERS,
    ).json()["proposals"]
    assert all(p["store_id"] == FLAGSHIP_ID for p in flag_listed)
    assert not any(p["store_id"] == OTHER_ID for p in flag_listed)


def test_review_trigger_with_only_store_id_uses_that_store_review(client, demo_env):
    res = client.post(
        "/agents/review-response/trigger",
        headers=HEADERS,
        json={"storeId": OTHER_ID},
    )
    assert res.status_code == 200
    body = res.json()
    assert body.get("skipped") is not True
    assert body.get("reason") != "Rating > 3, no response needed"
    runtime = body.get("_runtime") or {}
    assert (runtime.get("store_id") or body.get("store_id") or OTHER_ID) == OTHER_ID


def test_all_ops_agents_run_for_requested_store(client, demo_env):
    for agent_id, path in OPS_TRIGGERS:
        res = client.post(path, headers=HEADERS, json={"storeId": OTHER_ID})
        assert res.status_code == 200, f"{agent_id} {res.status_code} {res.text[:200]}"
        body = res.json()
        assert body.get("error") != "AGENT_TOKEN not configured", agent_id

    runs = client.get(f"/agent/runs?storeId={OTHER_ID}&limit=50", headers=HEADERS)
    assert runs.status_code == 200
    by_agent = {r.get("agent") for r in runs.json()["runs"]}
    missing = {agent_id for agent_id, _ in OPS_TRIGGERS} - by_agent
    assert not missing, f"no store-scoped run for {missing}"
    assert all(r.get("store_id") == OTHER_ID for r in runs.json()["runs"])


def _kitchen_counts(db_path):
    conn = sqlite3.connect(db_path)
    try:
        placeholders = ",".join("?" for _ in KITCHEN_STATUSES)
        rows = conn.execute(
            f"SELECT store_id, COUNT(*) FROM orders WHERE status IN ({placeholders}) GROUP BY store_id",
            KITCHEN_STATUSES,
        ).fetchall()
        return {sid: n for sid, n in rows}
    finally:
        conn.close()


def test_seed_kitchen_queues_are_not_a_fleet_wide_overload(demo_env):
    counts = _kitchen_counts(demo_env)
    assert counts.get(BASTILLE_ID, 0) > 15
    assert counts.get(FLAGSHIP_ID, 0) <= 15
    assert counts.get(OTHER_ID, 0) < 3
    overloaded = [sid for sid, n in counts.items() if n > 15]
    assert 1 <= len(overloaded) <= 8
    assert BASTILLE_ID in overloaded


def _pricing_text(body):
    chunks = [str(body.get("summary") or "")]
    for p in body.get("proposals") or []:
        chunks.append(str(p.get("summary") or ""))
        chunks.append(str(p.get("rationale") or ""))
        chunks.append(str((p.get("payload") or {}).get("message") or ""))
    runtime = body.get("_runtime") or {}
    for p in runtime.get("proposals") or []:
        chunks.append(str(p.get("summary") or ""))
        chunks.append(str(p.get("rationale") or ""))
    return "\n".join(chunks)


def test_pricing_trigger_does_not_copy_bastille_onto_other_stores(client, demo_env):
    flag = client.post(
        "/agents/dynamic-pricing/trigger",
        headers=HEADERS,
        json={"storeId": FLAGSHIP_ID},
    )
    assert flag.status_code == 200
    flag_body = flag.json()
    flag_text = _pricing_text(flag_body)
    for p in (flag_body.get("proposals") or []) + ((flag_body.get("_runtime") or {}).get("proposals") or []):
        assert p.get("store_id") == FLAGSHIP_ID
    assert "Bastille" not in flag_text
    assert "Belleville" not in flag_text

    bast = client.post(
        "/agents/dynamic-pricing/trigger",
        headers=HEADERS,
        json={"storeId": BASTILLE_ID},
    )
    assert bast.status_code == 200
    bast_body = bast.json()
    bast_text = _pricing_text(bast_body)
    bast_props = (bast_body.get("proposals") or []) or (
        (bast_body.get("_runtime") or {}).get("proposals") or []
    )
    assert bast_props, "Bastille must produce its own overload pricing proposal"
    assert all(p.get("store_id") == BASTILLE_ID for p in bast_props)
    assert "Bastille" in bast_text
    assert "Oberkampf" not in bast_text
    assert "Belleville" not in bast_text

    listed = client.get(
        f"/agent/proposals?status=PENDING&storeId={FLAGSHIP_ID}&limit=100",
        headers=HEADERS,
    ).json()["proposals"]
    pricing = [p for p in listed if p.get("type") == "SUGGEST_PRICE_ADJUSTMENT"]
    assert all(p["store_id"] == FLAGSHIP_ID for p in pricing)
    assert not any("Bastille" in ((p.get("summary") or "") + (p.get("rationale") or "")) for p in pricing)


LOUVRE_ID = "68a1f2c9e4b0a12345678901"


def _pricing_props(body):
    return (body.get("proposals") or []) or ((body.get("_runtime") or {}).get("proposals") or [])


def test_pricing_discount_lines_are_not_inventory_quantities(client, demo_env):
    res = client.post(
        "/agents/dynamic-pricing/trigger",
        headers=HEADERS,
        json={"storeId": LOUVRE_ID},
    )
    assert res.status_code == 200
    props = _pricing_props(res.json())
    assert props, "Louvre slow period should produce a discount proposal"
    items = (props[0].get("payload") or {}).get("items") or []
    assert items
    for item in items:
        assert item.get("percent") == 15
        assert item.get("direction") in ("discount", "decrease")
        assert "quantity" not in item
        assert item.get("unit") != "%"
        assert item.get("itemName")
        assert " · %" not in str(item.get("itemName"))


def test_shift_trigger_surfaces_roster_slots_not_a_counter_stub(client, demo_env):
    res = client.post(
        "/agents/shift-optimisation/trigger",
        headers=HEADERS,
        json={"storeId": LOUVRE_ID},
    )
    assert res.status_code == 200
    props = _pricing_props(res.json())
    assert props, "shift optimisation must emit a manager proposal"
    prop = props[0]
    assert prop.get("type") == "DRAFT_SHIFT_ROSTER"
    assert prop.get("store_id") == LOUVRE_ID
    assert "action(s) need review" not in (prop.get("summary") or "")
    items = (prop.get("payload") or {}).get("items") or []
    assert len(items) >= 7
    sample = items[0]
    assert sample.get("itemName") or sample.get("staffName")
    assert sample.get("role")
    assert sample.get("date")
    assert sample.get("startTime")
    assert sample.get("endTime")
    assert (prop.get("payload") or {}).get("source") != "rule_fallback"


def test_trigger_rejects_unknown_store_id(client, demo_env):
    """A garbage store_id (e.g. 's1', 'store-1') must be rejected before it
    reaches proposal creation — this is the root cause behind messy store_ids
    accumulating in the proposal store."""
    for bad_id in ("s1", "store-1", "not-a-real-store"):
        res = client.post(
            "/agents/inventory-reorder/trigger",
            headers=HEADERS,
            json={"storeId": bad_id},
        )
        assert res.status_code == 404, f"expected 404 for bad store_id {bad_id!r}, got {res.status_code}"

    # A real store_id must still work — validation isn't blocking everything.
    ok = client.post(
        "/agents/inventory-reorder/trigger",
        headers=HEADERS,
        json={"storeId": LOUVRE_ID},
    )
    assert ok.status_code == 200

    # Fleet-wide trigger (no storeId at all) must still work — validation only
    # applies to a non-empty store_id, never to the "run for every store" path.
    fleet = client.post(
        "/agents/inventory-reorder/trigger",
        headers=HEADERS,
        json={},
    )
    assert fleet.status_code == 200


def test_manager_chat_rejects_unknown_store_id(client, demo_env):
    res = client.post(
        "/agent/manager/chat",
        headers=HEADERS,
        json={"message": "check stock", "storeId": "store-1"},
    )
    assert res.status_code == 404
