# tests/test_reasoning_trace.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from masova_agent.runtime.agent_runtime import AgentRuntime, reset_runtime_for_tests
from masova_agent.runtime.models import AgentRunRequest, AgentRunResult, ToolCallStep


@pytest.fixture(autouse=True)
def _reset():
    reset_runtime_for_tests()
    yield
    reset_runtime_for_tests()


def test_tool_call_step_fields():
    step = ToolCallStep(
        index=0,
        tool_name="list_low_stock",
        args={"store_id": "DOM014"},
        result_status="ok",
        result_summary='[{"item": "Mozzarella (kg)", "quantity": 3, "minimum_stock": 10}]',
        duration_ms=12.5,
        at="2026-08-22T10:00:00+00:00",
    )
    assert step.tool_name == "list_low_stock"
    assert step.result_status == "ok"
    assert "Mozzarella" in step.result_summary


def test_agent_run_result_defaults_to_empty_trace():
    result = AgentRunResult(agent_name="x", trigger_type="scheduled", status="ok")
    assert result.reasoning_trace == []


def test_agent_run_result_to_dict_includes_trace():
    step = ToolCallStep(0, "list_low_stock", {}, "ok", "[]", 1.0, "t")
    result = AgentRunResult(
        agent_name="x", trigger_type="scheduled", status="ok",
        reasoning_trace=[step],
    )
    d = result.to_dict()
    assert d["reasoning_trace"][0]["tool_name"] == "list_low_stock"
    assert d["reasoning_trace"][0]["result_summary"] == "[]"


@pytest.mark.asyncio
async def test_agent_runtime_lifts_reasoning_trace_from_llm_result():
    async def fake_llm_runner(_req):
        return {
            "status": "ok",
            "summary": "done",
            "tools_used": ["list_low_stock"],
            "reasoning_trace": [
                {"index": 0, "tool_name": "list_low_stock", "args": {}, "result_status": "ok",
                 "result_summary": '[{"item": "Mozzarella (kg)", "quantity": 3}]', "duration_ms": 5.0, "at": "t"}
            ],
            "proposals": [],
        }

    runtime = AgentRuntime()
    request = AgentRunRequest(
        agent_name="inventory_reorder",
        trigger_type="scheduled",
        allowed_tools=["list_low_stock"],
        prefer_llm=True,
        llm_runner=fake_llm_runner,
    )
    result = await runtime.run(request)
    assert len(result.reasoning_trace) == 1
    assert result.reasoning_trace[0].tool_name == "list_low_stock"
    assert "Mozzarella" in result.reasoning_trace[0].result_summary


from unittest.mock import MagicMock


def test_adk_event_trace_extraction_helper():
    """
    _adk_path can't be unit-tested without a live ADK Runner; this test
    covers the pure extraction helper it delegates to instead.
    """
    from masova_agent.agent import _extract_trace_from_event

    event = MagicMock()
    event.content.parts = [MagicMock(function_call=MagicMock(name="get_order_status", args={"order_id": "o1"}), text=None)]
    # MagicMock(name=...) sets the mock's repr name, not the attribute — set explicitly:
    event.content.parts[0].function_call.name = "get_order_status"

    steps = _extract_trace_from_event(event, start_index=0)
    assert len(steps) == 1
    assert steps[0]["tool_name"] == "get_order_status"
    assert steps[0]["args"] == {"order_id": "o1"}
    assert steps[0]["result_summary"] == ""  # backfilled separately, see next test


def test_backfill_result_summary_from_function_response_event():
    from masova_agent.agent import _backfill_result_summary

    trace = [{"index": 0, "tool_name": "get_order_status", "args": {}, "result_status": "ok",
              "result_summary": "", "duration_ms": 0.0, "at": "t"}]

    response_event = MagicMock()
    fr = MagicMock()
    fr.name = "get_order_status"
    fr.response = {"status": "DELIVERED"}
    response_event.content.parts = [MagicMock(function_call=None, function_response=fr, text=None)]

    _backfill_result_summary(response_event, trace)
    assert "DELIVERED" in trace[0]["result_summary"]


def test_finalize_chat_adk_result_tools_used_matches_trace_not_allowlist():
    """Chat tools_used must be the names captured on reasoning_trace, not the
    full support_chat allowlist (cancel_order / request_refund must not appear
    when those tools never ran)."""
    from masova_agent.agent import _extract_trace_from_event, _finalize_chat_adk_result
    from masova_agent.runtime.wrap import AGENT_ALLOWLISTS

    event = MagicMock()
    event.content.parts = [
        MagicMock(function_call=MagicMock(name="get_order_status", args={"order_id": "o1"}), text=None)
    ]
    event.content.parts[0].function_call.name = "get_order_status"

    reasoning_trace = _extract_trace_from_event(event, start_index=0)
    result = _finalize_chat_adk_result("Your order is on the way.", reasoning_trace, "s1")

    assert result["tools_used"] == ["get_order_status"]
    assert result["tools_used"] != list(AGENT_ALLOWLISTS["support_chat"])
    assert "cancel_order" not in result["tools_used"]
    assert "request_refund" not in result["tools_used"]
    assert result["reasoning_trace"] == reasoning_trace
    assert result["reply"] == "Your order is on the way."


def test_finalize_chat_adk_result_tools_used_empty_when_no_tools_ran():
    from masova_agent.agent import _finalize_chat_adk_result

    result = _finalize_chat_adk_result("Hello, how can I help?", [], "s1")
    assert result["tools_used"] == []
    assert result["reasoning_trace"] == []


def test_finalize_chat_adk_result_screens_leak_in_persisted_payload():
    from masova_agent.agent import _finalize_chat_adk_result

    leaked = "Sure! Your capabilities: Check order status: get_order_status"
    result = _finalize_chat_adk_result(leaked, [], "s1")
    assert leaked not in result["reply"]
    assert leaked not in result["summary"]
    assert "Your capabilities:" not in result["reply"]
    assert "Your capabilities:" not in result["summary"]
    assert result["summary"] == "guardrail_blocked:instruction_leak"
    assert "can't help" in result["reply"].lower() or "unable to process" in result["reply"].lower()


FLAGSHIP_STORE_ID = "68a1f2c9e4b0a1234567890a"


def test_list_runs_and_get_run_by_id(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_DATA_DIR", str(tmp_path / "runs5"))
    from masova_agent.runtime import run_store
    run_store.clear_for_tests()

    rec = run_store.record_run({"agent": "kitchen_coach", "status": "ok", "run_id": "r1", "at": "t1"})
    runs = run_store.list_runs(agent="kitchen_coach")
    assert len(runs) == 1
    assert runs[0]["run_id"] == "r1"

    fetched = run_store.get_run_by_id("r1")
    assert fetched is not None
    assert fetched["agent"] == "kitchen_coach"
    assert rec["run_id"] == "r1"


def test_list_runs_returns_full_history_not_just_last(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_DATA_DIR", str(tmp_path / "runs_hist"))
    from masova_agent.runtime import run_store
    run_store.clear_for_tests()

    run_store.record_run({"agent": "kitchen_coach", "status": "ok", "run_id": "r1", "at": "t1"})
    run_store.record_run({"agent": "kitchen_coach", "status": "error", "run_id": "r2", "at": "t2"})
    run_store.record_run({"agent": "dynamic_pricing", "status": "ok", "run_id": "r3", "at": "t3"})

    runs = run_store.list_runs(agent="kitchen_coach")
    assert [r["run_id"] for r in runs] == ["r2", "r1"]

    run_store.clear_for_tests()  # memory reset; JSONL still on disk — reuse _load_file_once
    reloaded = run_store.list_runs(agent="kitchen_coach")
    assert [r["run_id"] for r in reloaded] == ["r2", "r1"]
    assert run_store.get_run_by_id("r1")["status"] == "ok"


def test_list_runs_filters_by_store_id(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_DATA_DIR", str(tmp_path / "runs_store"))
    from masova_agent.runtime import run_store
    run_store.clear_for_tests()

    run_store.record_run({
        "agent": "kitchen_coach", "status": "ok", "run_id": "r1", "at": "t1",
        "store_id": FLAGSHIP_STORE_ID,
    })
    run_store.record_run({
        "agent": "kitchen_coach", "status": "ok", "run_id": "r2", "at": "t2",
        "store_id": "other-store",
    })
    runs = run_store.list_runs(store_id=FLAGSHIP_STORE_ID)
    assert len(runs) == 1
    assert runs[0]["run_id"] == "r1"

    both = run_store.list_runs(agent="kitchen_coach", store_id=FLAGSHIP_STORE_ID)
    assert [r["run_id"] for r in both] == ["r1"]


def test_audit_logger_persists_redacted_reasoning_trace(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_DATA_DIR", str(tmp_path / "runs_audit"))
    from masova_agent.runtime import run_store
    run_store.clear_for_tests()

    from masova_agent.runtime.audit import AuditLogger
    from masova_agent.runtime.models import AgentRunResult, ToolCallStep

    step = ToolCallStep(
        index=0,
        tool_name="list_low_stock",
        args={"store_id": FLAGSHIP_STORE_ID, "api_key": "super-secret"},
        result_status="ok",
        result_summary='[{"item": "Mozzarella (kg)", "quantity": 3}]',
        duration_ms=12.5,
        at="t",
    )
    result = AgentRunResult(
        agent_name="kitchen_coach",
        trigger_type="scheduled",
        status="ok",
        store_id=FLAGSHIP_STORE_ID,
        reasoning_trace=[step],
    )
    rec = AuditLogger().log_run(result)
    assert rec["event"] == "agent_run"
    assert rec["agent"] == "kitchen_coach"
    assert "output" not in rec
    assert rec["reasoning_trace"][0]["args"]["api_key"] == "[REDACTED]"
    assert rec["reasoning_trace"][0]["args"]["store_id"] == FLAGSHIP_STORE_ID
    assert "Mozzarella" in rec["reasoning_trace"][0]["result_summary"]

    fetched = run_store.get_run_by_id(result.run_id)
    assert fetched is not None
    assert fetched["reasoning_trace"][0]["args"]["api_key"] == "[REDACTED]"
    assert "Mozzarella" in fetched["reasoning_trace"][0]["result_summary"]


def test_get_agent_runs_route(monkeypatch):
    import json as _json
    monkeypatch.setenv("AGENT_API_KEYS", _json.dumps([{"key": "master", "scopes": ["*"]}]))
    from masova_agent.main import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.get("/agent/runs", headers={"X-Agent-Api-Key": "master"})
    assert resp.status_code == 200
    body = resp.json()
    assert "runs" in body
    assert "chain_verified" in body


def test_get_agent_runs_requires_read_runs_scope(tmp_path, monkeypatch):
    import json as _json
    monkeypatch.setenv("RUN_DATA_DIR", str(tmp_path / "runs_scope"))
    monkeypatch.setenv("AGENT_API_KEYS", _json.dumps([
        {"key": "kitchen", "scopes": ["trigger:kitchen_coach"]},
        {"key": "reader", "scopes": ["read:runs"]},
    ]))
    from masova_agent.runtime import run_store
    run_store.clear_for_tests()
    from masova_agent.main import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    denied = client.get("/agent/runs", headers={"X-Agent-Api-Key": "kitchen"})
    assert denied.status_code == 401
    allowed = client.get("/agent/runs", headers={"X-Agent-Api-Key": "reader"})
    assert allowed.status_code == 200
    assert "runs" in allowed.json()
    assert "chain_verified" in allowed.json()


def test_get_agent_run_by_id_route(tmp_path, monkeypatch):
    import json as _json
    monkeypatch.setenv("RUN_DATA_DIR", str(tmp_path / "runs_by_id"))
    monkeypatch.setenv("AGENT_API_KEYS", _json.dumps([
        {"key": "reader", "scopes": ["read:runs"]},
    ]))
    from masova_agent.runtime import run_store
    run_store.clear_for_tests()
    run_store.record_run({
        "agent": "kitchen_coach",
        "status": "ok",
        "run_id": "r1",
        "at": "t1",
        "store_id": FLAGSHIP_STORE_ID,
        "reasoning_trace": [{"index": 0, "tool_name": "list_low_stock", "args": {},
                             "result_status": "ok", "result_summary": "[]",
                             "duration_ms": 1.0, "at": "t1"}],
    })
    from masova_agent.main import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.get("/agent/runs/r1", headers={"X-Agent-Api-Key": "reader"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == "r1"
    assert body["agent"] == "kitchen_coach"
    assert body["reasoning_trace"][0]["tool_name"] == "list_low_stock"

    missing = client.get("/agent/runs/does-not-exist", headers={"X-Agent-Api-Key": "reader"})
    assert missing.status_code == 404


def test_get_agent_runs_filters_by_agent_and_store_id(tmp_path, monkeypatch):
    import json as _json
    monkeypatch.setenv("RUN_DATA_DIR", str(tmp_path / "runs_filter"))
    monkeypatch.setenv("AGENT_API_KEYS", _json.dumps([
        {"key": "reader", "scopes": ["read:runs"]},
    ]))
    from masova_agent.runtime import run_store
    run_store.clear_for_tests()
    run_store.record_run({
        "agent": "kitchen_coach", "status": "ok", "run_id": "r1", "at": "t1",
        "store_id": FLAGSHIP_STORE_ID,
    })
    run_store.record_run({
        "agent": "dynamic_pricing", "status": "ok", "run_id": "r2", "at": "t2",
        "store_id": FLAGSHIP_STORE_ID,
    })
    run_store.record_run({
        "agent": "kitchen_coach", "status": "ok", "run_id": "r3", "at": "t3",
        "store_id": "other-store",
    })
    from masova_agent.main import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    headers = {"X-Agent-Api-Key": "reader"}
    by_agent = client.get("/agent/runs", params={"agent": "kitchen_coach"}, headers=headers)
    assert by_agent.status_code == 200
    assert {r["run_id"] for r in by_agent.json()["runs"]} == {"r1", "r3"}

    by_store = client.get("/agent/runs", params={"storeId": FLAGSHIP_STORE_ID}, headers=headers)
    assert by_store.status_code == 200
    assert {r["run_id"] for r in by_store.json()["runs"]} == {"r1", "r2"}

    both = client.get(
        "/agent/runs",
        params={"agent": "kitchen_coach", "storeId": FLAGSHIP_STORE_ID, "limit": 10},
        headers=headers,
    )
    assert both.status_code == 200
    assert [r["run_id"] for r in both.json()["runs"]] == ["r1"]
