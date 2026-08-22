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
