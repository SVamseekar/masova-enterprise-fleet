import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from masova_agent.runtime import registry, run_store
from masova_agent.runtime.wrap import AGENT_ALLOWLISTS
from masova_agent.scheduler.scheduler import register_jobs


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_DATA_DIR", str(tmp_path / "runs"))
    run_store.clear_for_tests()
    register_jobs()
    yield
    run_store.clear_for_tests()


def test_registry_returns_exactly_the_eight_agent_ids():
    entries = registry.build_registry()
    ids = {e["id"] for e in entries}
    assert ids == set(AGENT_ALLOWLISTS.keys())
    assert len(entries) == 8


def test_inventory_reorder_schedule_is_derived_from_scheduler():
    entries = {e["id"]: e for e in registry.build_registry()}
    entry = entries["inventory_reorder"]
    assert entry["trigger_type"] == "interval"
    assert "6h" in entry["schedule"]


def test_demand_forecast_schedule_is_cron_derived():
    entries = {e["id"]: e for e in registry.build_registry()}
    entry = entries["demand_forecast"]
    assert entry["trigger_type"] == "cron"
    assert entry["schedule"]  # non-empty, derived from the real cron fields


def test_support_chat_has_no_scheduler_job():
    entries = {e["id"]: e for e in registry.build_registry()}
    entry = entries["support_chat"]
    assert entry["category"] == "chat"
    assert entry["trigger_type"] == "chat"
    assert entry["schedule"] is None


def test_review_response_is_event_triggered():
    entries = {e["id"]: e for e in registry.build_registry()}
    entry = entries["review_response"]
    assert entry["category"] == "event"
    assert entry["trigger_type"] == "rabbitmq+manual"


def test_tool_allowlist_tiers_never_include_execute():
    entries = registry.build_registry()
    for e in entries:
        for tool in e["tool_allowlist"]:
            assert tool["tier"] != "EXECUTE"


def test_last_run_is_none_before_any_run():
    entries = {e["id"]: e for e in registry.build_registry()}
    assert entries["kitchen_coach"]["last_run"] is None


def test_last_run_reflects_persisted_record():
    run_store.record_run({
        "agent": "kitchen_coach",
        "status": "ok",
        "used_fallback": False,
        "trigger_type": "scheduled",
        "at": "2026-08-22T11:00:00+00:00",
    })
    entries = {e["id"]: e for e in registry.build_registry()}
    assert entries["kitchen_coach"]["last_run"]["status"] == "ok"


def test_no_version_field_present():
    entries = registry.build_registry()
    for e in entries:
        assert "version" not in e


def test_missing_scheduler_job_yields_null_trigger_type():
    """Missing scheduler job for a scheduled agent returns None (not "unknown")."""
    from masova_agent.scheduler.scheduler import get_scheduler

    scheduler = get_scheduler()
    # Remove all jobs with id="demand_forecast" (may be duplicates from fixture re-runs)
    removed_jobs = []
    for job in scheduler.get_jobs():
        if job.id == "demand_forecast":
            removed_jobs.append(job)
            scheduler.remove_job("demand_forecast")

    try:
        entries = {e["id"]: e for e in registry.build_registry()}
        entry = entries["demand_forecast"]

        # Vocabulary constraint: trigger_type must be None (not "unknown")
        assert entry["trigger_type"] is None
        assert entry["schedule"] is None
    finally:
        # Restore the removed jobs for subsequent tests
        for job in removed_jobs:
            scheduler.add_job(
                job.func,
                trigger=job.trigger,
                id="demand_forecast",
                name="Demand Forecasting Agent",
                replace_existing=True,
            )


# ---------------------------------------------------------------------------
# GET /agents route tests
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient


def test_get_agents_requires_api_key(monkeypatch):
    monkeypatch.setenv("AGENT_TRIGGER_API_KEY", "test-key-123")
    from masova_agent.main import app

    client = TestClient(app)
    resp = client.get("/agents")
    assert resp.status_code == 401


def test_get_agents_returns_catalog_with_valid_key(monkeypatch):
    monkeypatch.setenv("AGENT_TRIGGER_API_KEY", "test-key-123")
    from masova_agent.main import app

    client = TestClient(app)
    resp = client.get("/agents", headers={"X-Agent-Api-Key": "test-key-123"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["agents"]) == 8
    assert {a["id"] for a in body["agents"]} == set(AGENT_ALLOWLISTS.keys())


# ---------------------------------------------------------------------------
# ENDPOINT_MAP sync with live app routes
# ---------------------------------------------------------------------------


def test_endpoint_map_values_are_real_app_routes():
    """Every hand-authored ENDPOINT_MAP path must exist on the live app,
    method-aware (POST for chat and all trigger endpoints), so a renamed
    route fails this test instead of silently 404ing while the catalog
    still advertises the old path."""
    from masova_agent.main import app
    from starlette.routing import Route as StarletteRoute

    live_routes: set[tuple[str, str]] = set()
    for route in app.routes:
        if not isinstance(route, StarletteRoute):
            continue
        for method in getattr(route, "methods", None) or set():
            live_routes.add((method, route.path))

    for agent_id, path in registry.ENDPOINT_MAP.items():
        assert ("POST", path) in live_routes, (
            f"ENDPOINT_MAP[{agent_id!r}] = {path!r} is not a real POST route on the app"
        )


# ---------------------------------------------------------------------------
# AGENT_LABELS / ENDPOINT_MAP / AGENT_ALLOWLISTS stay pinned together
# ---------------------------------------------------------------------------


def test_agent_maps_are_pinned_together():
    """A future 9th agent added to AGENT_ALLOWLISTS without a matching
    AGENT_LABELS/ENDPOINT_MAP entry must fail CI, not silently fall back
    to a guessed label and an empty endpoint."""
    assert set(registry.AGENT_LABELS.keys()) == set(registry.ENDPOINT_MAP.keys()) == set(AGENT_ALLOWLISTS.keys())


# ---------------------------------------------------------------------------
# Cron schedule strings: no noisy second=0, timezone always present
# ---------------------------------------------------------------------------


def test_cron_schedule_has_no_bare_second_zero():
    entries = {e["id"]: e for e in registry.build_registry()}
    for agent_id in ("demand_forecast", "churn_prevention", "shift_optimisation", "kitchen_coach", "dynamic_pricing"):
        entry = entries[agent_id]
        if entry["trigger_type"] != "cron":
            continue
        assert "second=0" not in entry["schedule"], entry["schedule"]


def test_cron_schedule_includes_trigger_timezone():
    from masova_agent.scheduler.scheduler import get_scheduler

    jobs_by_id = {job.id: job for job in get_scheduler().get_jobs()}
    entries = {e["id"]: e for e in registry.build_registry()}

    entry = entries["demand_forecast"]
    tz = str(jobs_by_id["demand_forecast"].trigger.timezone)
    assert tz in entry["schedule"]


def test_interval_schedule_includes_trigger_timezone():
    from masova_agent.scheduler.scheduler import get_scheduler

    jobs_by_id = {job.id: job for job in get_scheduler().get_jobs()}
    entries = {e["id"]: e for e in registry.build_registry()}

    entry = entries["inventory_reorder"]
    tz = str(jobs_by_id["inventory_reorder"].trigger.timezone)
    assert tz in entry["schedule"]
