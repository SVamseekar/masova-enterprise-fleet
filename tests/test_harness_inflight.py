import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from masova_agent.runtime.agent_runtime import AgentRuntime, reset_runtime_for_tests
from masova_agent.runtime.models import AgentRunRequest
from masova_agent.runtime import run_store


@pytest.mark.asyncio
async def test_run_is_visible_as_running_before_fallback_finishes(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_DATA_DIR", str(tmp_path))
    run_store.clear_for_tests()
    reset_runtime_for_tests()
    started = asyncio.Event()

    async def slow_fallback():
        started.set()
        await asyncio.sleep(0.2)
        return {"status": "ok", "summary": "done", "tools_used": ["list_low_stock"]}

    runtime = AgentRuntime()
    req = AgentRunRequest(
        agent_name="inventory_reorder",
        trigger_type="manual",
        store_id="store-1",
        allowed_tools=["list_low_stock"],
        fallback=slow_fallback,
        prefer_llm=False,
    )
    task = asyncio.create_task(runtime.run(req))
    await started.wait()
    await asyncio.sleep(0.05)
    running = [r for r in run_store.list_runs(agent="inventory_reorder") if r.get("status") == "running"]
    assert running, "expected an in-flight running record"
    assert running[0].get("run_id")
    result = await task
    assert result.status == "ok"
    final = run_store.get_run_by_id(result.run_id)
    assert final["status"] == "ok"


@pytest.mark.asyncio
async def test_scripted_loop_upserts_trace_after_each_tool(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_DATA_DIR", str(tmp_path))
    run_store.clear_for_tests()
    from masova_agent.runtime.ops_llm import run_scripted_tool_loop

    gate = asyncio.Event()

    async def t1(**_):
        return {"ok": True, "n": 1}

    async def t2(**_):
        gate.set()
        await asyncio.sleep(0.25)
        return {"ok": True, "n": 2}

    req = AgentRunRequest(
        agent_name="inventory_reorder",
        trigger_type="manual",
        store_id="s1",
        allowed_tools=["t1", "t2"],
        run_id="run-mid",
        prefer_llm=True,
    )
    run_store.upsert_run({
        "run_id": "run-mid", "agent": "inventory_reorder",
        "status": "running", "store_id": "s1", "reasoning_trace": [],
    })
    task = asyncio.create_task(run_scripted_tool_loop(
        req,
        [{"tool": "t1", "args": {}}, {"tool": "t2", "args": {}}],
        {"t1": t1, "t2": t2},
    ))
    await gate.wait()
    rec = run_store.get_run_by_id("run-mid")
    names = [s.get("tool_name") or s.get("tool") for s in (rec.get("reasoning_trace") or [])]
    assert "t1" in names
    await task


def test_chain_report_counts_terminal_records_only(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_DATA_DIR", str(tmp_path))
    run_store.clear_for_tests()
    run_store.upsert_run({"run_id": "r1", "agent": "inventory_reorder", "status": "running"})
    run_store.record_run({"agent": "inventory_reorder", "run_id": "r1", "status": "ok"})
    report = run_store.chain_report()
    assert report["verified"] is True
    assert report["length"] == 1
    assert isinstance(report["tip"], str) and len(report["tip"]) >= 8
