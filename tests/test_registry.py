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
