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
