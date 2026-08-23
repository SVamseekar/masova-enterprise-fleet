# Reasoning-Chain Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture a structured, ordered, tamper-evident trace of every tool call an agent makes during a run — not just the flat `tools_used` list — and expose it via a new `GET /agent/runs` endpoint.

**Architecture:** A `ToolCallStep` dataclass (`runtime/models.py`) is populated at the real call sites — `ops_llm.py`'s two tool loops for ops agents, `agent.py`'s ADK event loop for chat — timed and recorded as each call actually happens. `AgentRuntime.run()` lifts `reasoning_trace` out of the loop's output dict onto `AgentRunResult`, same pattern as the existing `tools_used` handling. `run_store.py` (built in Phase 1) gains a SHA-256 hash chain over persisted records for tamper-evidence.

**Tech Stack:** Python 3.11, hashlib (stdlib), FastAPI.

**Spec:** `docs/superpowers/specs/2026-08-22-reasoning-chain-observability-design.md`

**Inherits:** `docs/superpowers/specs/2026-08-22-hackathon-constraints.md`. Spec revised 2026-08-22.

## Global Constraints

- Depends on Phase 1's `runtime/run_store.py` and Phase 2's `require_scope` — the new endpoints are gated with `require_scope("read:runs")` (not `read:registry`).
- `result_summary` is the demo's data-provenance field: it must contain the real tool return (truncated, redacted), e.g. mozzarella stock from SQLite, so a judge can match it to `GET /agent/demo/tables/inventory`.
- Trace steps must come from real call events as they happen — never reconstructed after the fact from `tools_used`.
- A tool call that raises is still recorded (`result_status: "error"`), never dropped.
- Test import style: `from masova_agent.x import y`.
- In test fixtures, store_id is `68a1f2c9e4b0a1234567890a` (not `DOM014`).

---

### Task 1: `ToolCallStep` model + `AgentRunResult.reasoning_trace`

**Files:**
- Modify: `src/masova_agent/runtime/models.py` (add `ToolCallStep`, extend `AgentRunResult`)
- Modify: `src/masova_agent/runtime/agent_runtime.py:82-92` (`_extract_proposals`-adjacent handling — pop `reasoning_trace` from `output`)
- Test: `tests/test_reasoning_trace.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `ToolCallStep(index, tool_name, args, result_status, result_summary, duration_ms, at)`, `AgentRunResult.reasoning_trace: list[ToolCallStep]` — Task 2 and 3 populate this by returning `"reasoning_trace": [...]` (list of dicts) in their loop's output dict, which this task's `AgentRuntime.run()` change converts. `result_summary` is a truncated, redacted repr of what the tool actually returned — the field that lets a demo trace an agent's decision back to real data, not just a pass/fail status.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reasoning_trace.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from masova_agent.runtime.models import ToolCallStep, AgentRunResult


def test_tool_call_step_fields():
    step = ToolCallStep(
        index=0,
        tool_name="list_low_stock",
        args={"store_id": "68a1f2c9e4b0a1234567890a"},
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reasoning_trace.py -v`
Expected: FAIL with `ImportError: cannot import name 'ToolCallStep'`

- [ ] **Step 3: Add `ToolCallStep` and extend `AgentRunResult`**

In `src/masova_agent/runtime/models.py`, add near the top (after the
`ToolRisk` dataclass, before `_utc_now_iso`):

```python
@dataclass
class ToolCallStep:
    """One recorded tool invocation within an agent run's reasoning chain."""

    index: int
    tool_name: str
    args: dict[str, Any]
    result_status: str  # "ok" | "error"
    result_summary: str  # truncated (500 char), redacted repr of the tool's actual return value
    duration_ms: float
    at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "tool_name": self.tool_name,
            "args": self.args,
            "result_status": self.result_status,
            "result_summary": self.result_summary,
            "duration_ms": round(self.duration_ms, 2),
            "at": self.at,
        }
```

Then modify `AgentRunResult` (around line 137-151) to add the field and
update `to_dict`:

```python
@dataclass
class AgentRunResult:
    """Outcome of a unified agent run."""

    agent_name: str
    trigger_type: str
    status: str  # ok | error | skipped
    used_fallback: bool = False
    store_id: Optional[str] = None
    summary: str = ""
    proposals: list[ActionProposal] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    reasoning_trace: list["ToolCallStep"] = field(default_factory=list)
    output: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    latency_ms: float = 0.0
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "agent_name": self.agent_name,
            "trigger_type": self.trigger_type,
            "status": self.status,
            "used_fallback": self.used_fallback,
            "store_id": self.store_id,
            "summary": self.summary,
            "proposals": [p.to_dict() for p in self.proposals],
            "tools_used": self.tools_used,
            "reasoning_trace": [s.to_dict() for s in self.reasoning_trace],
            "output": self.output,
            "error": self.error,
            "latency_ms": self.latency_ms,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_reasoning_trace.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Lift `reasoning_trace` out of the loop output in `AgentRuntime.run()`**

In `src/masova_agent/runtime/agent_runtime.py`, both branches that build
`output` and `tools_used` (the `if llm_result is not None:` branch around
line 82 and the `elif request.fallback is not None:` branch around line 88)
already do `tools_used = list(output.pop("tools_used", []) or [])`. Add the
matching line right after each, and thread the result into
`AgentRunResult`:

```python
            if llm_result is not None:
                output = dict(llm_result)
                tools_used = list(output.pop("tools_used", []) or [])
                reasoning_trace = self._extract_trace(output.pop("reasoning_trace", []))
                proposals = self._extract_proposals(output)
                summary = str(output.get("summary") or output.get("status") or "llm_ok")
            elif request.fallback is not None:
                used_fallback = True
                fb = await self._call_maybe_async(request.fallback)
                if not isinstance(fb, dict):
                    fb = {"result": fb}
                output = dict(fb)
                tools_used = list(output.pop("tools_used", []) or [])
                reasoning_trace = self._extract_trace(output.pop("reasoning_trace", []))
                proposals = self._extract_proposals(output)
                ...
```

Initialize `reasoning_trace: list[ToolCallStep] = []` alongside the other
accumulator variables near the top of `run()` (next to `tools_used: list[str] = []`),
and pass it into the final `AgentRunResult(...)` construction:
`reasoning_trace=reasoning_trace,`.

Add the helper method (near `_extract_proposals`):

```python
    def _extract_trace(self, raw: list[Any]) -> list[ToolCallStep]:
        out: list[ToolCallStep] = []
        for i, item in enumerate(raw):
            if isinstance(item, ToolCallStep):
                out.append(item)
            elif isinstance(item, dict):
                out.append(ToolCallStep(
                    index=item.get("index", i),
                    tool_name=str(item.get("tool_name") or item.get("tool") or ""),
                    args=dict(item.get("args") or {}),
                    result_status=str(item.get("result_status") or "ok"),
                    result_summary=str(item.get("result_summary") or "")[:500],
                    duration_ms=float(item.get("duration_ms") or 0.0),
                    at=str(item.get("at") or ""),
                ))
        return out
```

Add `ToolCallStep` to the `from .models import (...)` block at the top of
`agent_runtime.py`.

- [ ] **Step 6: Add a test proving `AgentRuntime.run()` threads the trace through**

Append to `tests/test_reasoning_trace.py`:

```python
import pytest

from masova_agent.runtime.agent_runtime import AgentRuntime, reset_runtime_for_tests
from masova_agent.runtime.models import AgentRunRequest


@pytest.fixture(autouse=True)
def _reset():
    reset_runtime_for_tests()
    yield
    reset_runtime_for_tests()


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
```

(Check `tests/conftest.py` / existing async tests, e.g.
`tests/test_runtime.py`, for whether `pytest-asyncio` is already configured
— if `@pytest.mark.asyncio` isn't recognized, match whatever pattern the
existing async tests in this repo use instead, since this repo already has
async runtime tests passing today.)

- [ ] **Step 7: Run the full trace test file**

Run: `pytest tests/test_reasoning_trace.py -v`
Expected: PASS (4 tests)

- [ ] **Step 8: Commit**

```bash
git add src/masova_agent/runtime/models.py src/masova_agent/runtime/agent_runtime.py tests/test_reasoning_trace.py
git commit -m "feat: add structured ToolCallStep reasoning trace to AgentRunResult"
```

---

### Task 2: Capture trace steps in the ops tool loops (`ops_llm.py`)

**Files:**
- Modify: `src/masova_agent/runtime/ops_llm.py` (`run_scripted_tool_loop` ~L114-173, `run_genai_tool_loop` ~L176-350)
- Test: `tests/test_ops_llm_tools.py` (existing file — append trace assertions to the existing scripted-plan tests)

**Interfaces:**
- Consumes: `ToolCallStep`-shaped dicts are what this task returns (not the dataclass itself — `ops_llm.py` stays dataclass-free, matching its existing plain-dict style; Task 1's `_extract_trace` converts).
- Produces: both loop functions' return dict gains `"reasoning_trace": list[dict]`, consumed by Task 1's `AgentRuntime._extract_trace`.

- [ ] **Step 1: Write the failing test**

Find the existing scripted-plan test in `tests/test_ops_llm_tools.py` (the
low-stock → draft PO golden path referenced in `AGENT_PLATFORM.md`'s
industry eval list) and add, in the same style as its existing assertions:

```python
def test_scripted_tool_loop_produces_reasoning_trace():
    # Reuse this file's existing plan/tools fixtures for the low-stock
    # scenario (see the existing test above this one for the exact
    # request/plan/tools construction already used in this file).
    result = asyncio.run(run_scripted_tool_loop(request, plan, tools))
    trace = result["reasoning_trace"]
    assert len(trace) == len(result["tools_used"])
    assert trace[0]["index"] == 0
    assert trace[0]["tool_name"] == result["tools_used"][0]
    assert trace[0]["result_status"] == "ok"
    assert trace[0]["duration_ms"] >= 0
    assert trace[0]["result_summary"]  # non-empty — real data from the tool's actual return value
```

(This step assumes `tests/test_ops_llm_tools.py` already has a request/plan/
tools fixture for a scripted golden path — reuse it exactly as the existing
adjacent test does, rather than constructing a new one, so this test's
setup matches the file's established conventions.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ops_llm_tools.py -v -k reasoning_trace`
Expected: FAIL with `KeyError: 'reasoning_trace'`

- [ ] **Step 3: Instrument `run_scripted_tool_loop`**

In `src/masova_agent/runtime/ops_llm.py`, modify the loop body (~L131-151):

Add this helper near the top of the module (used by both loops below):

```python
def _summarize_result(result: Any) -> str:
    """Truncated, JSON-ish repr of a tool's actual return value — this is
    what lets a reasoning trace show real data, not just a status flag."""
    try:
        text = json.dumps(result, default=str)
    except Exception:
        text = str(result)
    return text[:500]
```

(`json` is already imported at the top of `ops_llm.py`.)

```python
    import time
    from .models import _utc_now_iso  # already used elsewhere in this module's siblings

    trace: list[dict[str, Any]] = []

    for step in plan[:max_calls]:
        name = step.get("tool") or step.get("name")
        args = step.get("args") or step.get("arguments") or {}
        if not name:
            continue
        if name not in allowed or not policy.is_allowed(name, allowed):
            tool_results.append({
                "tool": name,
                "result": {"ok": False, "error": "tool_not_allowed"},
            })
            continue
        fn = tools.get(name)
        if fn is None:
            tool_results.append({
                "tool": name,
                "result": {"ok": False, "error": "unknown_tool"},
            })
            continue
        started = time.perf_counter()
        result = await invoke_tool(fn, args if isinstance(args, dict) else {})
        duration_ms = (time.perf_counter() - started) * 1000
        tools_used.append(name)
        tool_results.append({"tool": name, "args": args, "result": result})
        trace.append({
            "index": len(trace),
            "tool_name": name,
            "args": args,
            "result_status": "error" if isinstance(result, dict) and result.get("error") else "ok",
            "result_summary": _summarize_result(result),
            "duration_ms": duration_ms,
            "at": _utc_now_iso(),
        })
```

And add `"reasoning_trace": trace,` to the function's final return dict
(alongside the existing `"tools_used": tools_used,` line ~L168).

- [ ] **Step 4: Instrument `run_genai_tool_loop`**

The tool-execution block (~L296-319) already computes `result` per call.
Wrap it with timing and append to a `trace` list initialized alongside
`tools_used`/`tool_results` (~L251-252):

```python
    tools_used: list[str] = []
    tool_results: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    final_text = ""
    calls = 0
```

Inside the `for name, args in fn_calls:` loop:

```python
        for name, args in fn_calls:
            calls += 1
            if calls > max_calls:
                break
            started = time.perf_counter()
            if name not in allowed or not policy.is_allowed(name, allowed):
                result = {"ok": False, "error": "tool_not_allowed"}
            else:
                fn = tools.get(name)
                if fn is None:
                    result = {"ok": False, "error": "unknown_tool"}
                else:
                    result = await invoke_tool(fn, args if isinstance(args, dict) else {})
                    tools_used.append(name)
            duration_ms = (time.perf_counter() - started) * 1000
            tool_results.append({"tool": name, "args": args, "result": result})
            trace.append({
                "index": len(trace),
                "tool_name": name,
                "args": args,
                "result_status": "error" if isinstance(result, dict) and result.get("error") else "ok",
                "result_summary": _summarize_result(result),
                "duration_ms": duration_ms,
                "at": _utc_now_iso(),
            })
            response_parts.append(
                genai_types.Part(
                    function_response=genai_types.FunctionResponse(
                        name=name,
                        response=result if isinstance(result, dict) else {"result": result},
                    )
                )
            )
```

Add `"reasoning_trace": trace,` to the function's final `output = {...}`
dict (alongside `"tools_used": tools_used,` ~L340). Add `import time` and
`from .models import _utc_now_iso` to the module's existing imports at the
top of the file if not already present (it already imports `from .models
import AgentRunRequest`, so extend that import line).

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_ops_llm_tools.py -v`
Expected: PASS, including the new trace test, with no regressions in the
existing golden-path tests (they don't assert against the output dict's
exact key set, only specific keys, per the existing test style)

- [ ] **Step 6: Commit**

```bash
git add src/masova_agent/runtime/ops_llm.py tests/test_ops_llm_tools.py
git commit -m "feat: capture per-tool-call reasoning trace in the ops tool loops"
```

---

### Task 3: Capture trace steps in the chat (ADK) path (`agent.py`)

**Files:**
- Modify: `src/masova_agent/agent.py:118-146` (`_adk_path`)
- Test: `tests/test_reasoning_trace.py` (append)

**Interfaces:**
- Consumes: nothing new beyond what `_adk_path` already reads from ADK's
  `runner.run(...)` event stream.
- Produces: `_adk_path()`'s returned dict gains `"reasoning_trace": list[dict]`,
  same shape as Task 2, consumed by the same `AgentRuntime._extract_trace`
  from Task 1 (chat already routes through `AgentRuntime.run()` via
  `run_ops_agent`, so no new wiring is needed there).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_reasoning_trace.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reasoning_trace.py -v -k "adk_event_trace or backfill_result_summary"`
Expected: FAIL with `ImportError: cannot import name '_extract_trace_from_event'`

- [ ] **Step 3: Add the extraction helpers and wire them into `_adk_path`**

In `src/masova_agent/agent.py`, add near the top-level functions (after
`_resolve_model`, before `root_agent = LlmAgent(...)`):

```python
def _extract_trace_from_event(event, start_index: int) -> list[dict]:
    """Pull ToolCallStep-shaped dicts out of one ADK Runner event's function
    calls. result_summary starts empty — ADK emits the call and its result
    in separate events, so _backfill_result_summary fills it in once the
    matching function_response event arrives."""
    from .runtime.models import _utc_now_iso

    steps: list[dict] = []
    content = getattr(event, "content", None)
    parts = getattr(content, "parts", None) or []
    for part in parts:
        fc = getattr(part, "function_call", None)
        if fc and getattr(fc, "name", None):
            steps.append({
                "index": start_index + len(steps),
                "tool_name": fc.name,
                "args": dict(getattr(fc, "args", None) or {}),
                "result_status": "ok",
                "result_summary": "",
                "duration_ms": 0.0,
                "at": _utc_now_iso(),
            })
    return steps


def _backfill_result_summary(event, trace: list[dict]) -> None:
    """Scan one event's function_response parts and fill in the most recent
    matching trace step's result_summary — this is what lets the chat
    path's trace show real returned data, not just that a call happened."""
    import json

    content = getattr(event, "content", None)
    parts = getattr(content, "parts", None) or []
    for part in parts:
        fr = getattr(part, "function_response", None)
        if fr and getattr(fr, "name", None):
            for step in reversed(trace):
                if step["tool_name"] == fr.name and not step["result_summary"]:
                    try:
                        step["result_summary"] = json.dumps(fr.response, default=str)[:500]
                    except Exception:
                        step["result_summary"] = str(fr.response)[:500]
                    break
```

(`duration_ms` stays `0.0` — ADK's `Runner.run()` doesn't expose per-call
timing the way `ops_llm.py`'s direct `invoke_tool` calls do. This is a
real, documented limitation, not a fabricated value; `result_summary`
doesn't have the same limitation since ADK does expose the response
payload, just in a separate event, which `_backfill_result_summary`
reconciles.)

Modify `_adk_path()` (~L118-146):

```python
    async def _adk_path():
        runner = Runner(
            agent=root_agent,
            app_name="masova_support",
            session_service=_adk_session_service,
        )
        user_content = genai_types.Content(
            role="user",
            parts=[genai_types.Part(text=message)],
        )
        response_text = ""
        reasoning_trace: list[dict] = []
        for event in runner.run(
            user_id=user_id,
            session_id=actual_session_id,
            new_message=user_content,
        ):
            reasoning_trace.extend(_extract_trace_from_event(event, len(reasoning_trace)))
            _backfill_result_summary(event, reasoning_trace)
            if hasattr(event, "is_final_response") and event.is_final_response():
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if hasattr(part, "text") and part.text:
                            response_text += part.text
        reply = response_text.strip()
        return {
            "status": "ok",
            "reply": reply,
            "summary": (reply[:200] if reply else "empty"),
            "session_id": actual_session_id,
            "tools_used": list(AGENT_ALLOWLISTS.get("support_chat", [])),
            "reasoning_trace": reasoning_trace,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_reasoning_trace.py -v`
Expected: PASS (6 tests total)

- [ ] **Step 5: Run the full test suite to check for regressions**

Run: `pytest tests/ -v --ignore=tests/test_scenarios.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/masova_agent/agent.py tests/test_reasoning_trace.py
git commit -m "feat: capture reasoning trace steps from the chat agent's ADK event stream"
```

---

### Task 4: Hash chain over persisted run records

**Files:**
- Modify: `src/masova_agent/runtime/run_store.py` (from Phase 1)
- Test: `tests/test_run_store.py` (append)

**Interfaces:**
- Consumes: `record_run(record: dict)` (Phase 1, this task changes its internal
  behavior but keeps the same signature).
- Produces: `verify_chain(agent_name: str | None = None) -> bool` — Task 5's
  endpoint depends on this exact name and signature.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_run_store.py`:

```python
def test_verify_chain_true_on_untouched_store():
    run_store.record_run({"agent": "a", "status": "ok", "at": "t1"})
    run_store.record_run({"agent": "b", "status": "ok", "at": "t2"})
    assert run_store.verify_chain() is True


def test_verify_chain_false_after_tampering(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_DATA_DIR", str(tmp_path / "runs4"))
    run_store.clear_for_tests()
    run_store.record_run({"agent": "a", "status": "ok", "at": "t1"})

    path = run_store._jsonl_path()
    lines = path.read_text(encoding="utf-8").splitlines()
    import json as _json
    row = _json.loads(lines[0])
    row["status"] = "tampered"  # content changed, record_hash NOT recomputed
    path.write_text(_json.dumps(row) + "\n", encoding="utf-8")

    run_store.clear_for_tests()  # force reload from the tampered file
    assert run_store.verify_chain() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_run_store.py -v -k verify_chain`
Expected: FAIL with `AttributeError: module ... has no attribute 'verify_chain'`

- [ ] **Step 3: Add hashing to `record_run` and add `verify_chain`**

Modify `src/masova_agent/runtime/run_store.py`:

```python
import hashlib

_last_hash: str = "genesis"


def _canonical_json(record: dict[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)


def _compute_hash(prev_hash: str, record: dict[str, Any]) -> str:
    payload = prev_hash + _canonical_json(record)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def record_run(record: dict[str, Any]) -> dict[str, Any]:
    global _last_hash
    agent = str(record.get("agent") or record.get("agent_name") or "")
    if not agent:
        raise ValueError("record_run requires a non-empty 'agent' key")
    rec = dict(record)
    rec["agent"] = agent
    with _lock:
        prev_hash = _last_hash
        record_hash = _compute_hash(prev_hash, rec)
        rec["prev_hash"] = prev_hash
        rec["record_hash"] = record_hash
        _last_hash = record_hash
        _by_agent[agent] = rec
        try:
            d = _data_dir()
            d.mkdir(parents=True, exist_ok=True)
            with open(_jsonl_path(), "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, default=str) + "\n")
        except Exception as e:
            logger.warning("run record file append failed: %s", e)
    return rec


def verify_chain(agent_name: Optional[str] = None) -> bool:
    path = _jsonl_path()
    if not path.exists():
        return True
    prev = "genesis"
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if agent_name and row.get("agent") != agent_name:
                    continue
                claimed_prev = row.get("prev_hash", "")
                claimed_hash = row.get("record_hash", "")
                body = {k: v for k, v in row.items() if k not in ("prev_hash", "record_hash")}
                expected = _compute_hash(claimed_prev, body)
                if claimed_prev != prev or claimed_hash != expected:
                    return False
                prev = claimed_hash
    except Exception as e:
        logger.warning("chain verification failed to read file: %s", e)
        return False
    return True
```

`clear_for_tests()` must also reset `_last_hash`:

```python
def clear_for_tests() -> None:
    global _loaded, _last_hash
    with _lock:
        _by_agent.clear()
    _loaded = False
    _last_hash = "genesis"
```

Note: when `agent_name` filters the chain, `verify_chain` still walks the
*global* `prev`/hash sequence (the chain is over the whole file, not
per-agent) — the filter only decides which rows get checked, not a
separate per-agent chain. This matches the spec's tamper-evidence goal:
one file, one chain, any row's tampering is detectable regardless of which
agent it belongs to.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_run_store.py -v`
Expected: PASS (8 tests total)

- [ ] **Step 5: Run the full test suite to check for regressions**

Run: `pytest tests/ -v --ignore=tests/test_scenarios.py`
Expected: PASS — `get_last_run` still works since `record_hash`/`prev_hash`
are just extra keys on the same dict, not a shape change existing callers
depend on.

- [ ] **Step 6: Commit**

```bash
git add src/masova_agent/runtime/run_store.py tests/test_run_store.py
git commit -m "feat: hash-chain persisted run records for tamper-evidence"
```

---

### Task 5: `GET /agent/runs` and `GET /agent/runs/{run_id}`

**Files:**
- Modify: `src/masova_agent/main.py`
- Modify: `src/masova_agent/runtime/run_store.py` (add `list_runs`, `get_run_by_id`)
- Modify: `docs/AGENT_PLATFORM.md`
- Test: `tests/test_reasoning_trace.py` (append route tests)

**Interfaces:**
- Consumes: `verify_chain()` (Task 4), `require_scope("read:runs")` (Phase 2).
- Produces: `list_runs(agent=None, limit=100) -> list[dict]`, `get_run_by_id(run_id: str) -> dict | None` — new public functions on `run_store.py`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_reasoning_trace.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reasoning_trace.py -v -k "list_runs or get_agent_runs"`
Expected: FAIL — `list_runs`/`get_run_by_id` don't exist yet, route 404s

- [ ] **Step 3: Add `list_runs` and `get_run_by_id` to `run_store.py`**

```python
def list_runs(*, agent: Optional[str] = None, limit: int = 100) -> list[dict[str, Any]]:
    _load_all_records()
    rows = list(_all_records)
    if agent:
        rows = [r for r in rows if r.get("agent") == agent]
    rows.sort(key=lambda r: r.get("at") or "", reverse=True)
    return rows[: max(1, min(limit, 500))]


def get_run_by_id(run_id: str) -> Optional[dict[str, Any]]:
    _load_all_records()
    for row in reversed(_all_records):
        if row.get("run_id") == run_id:
            return dict(row)
    return None
```

These need every historical record, not just the latest per agent (unlike
`_by_agent`) — add a module-level `_all_records: list[dict[str, Any]] = []`
appended to inside `record_run` (alongside `_by_agent[agent] = rec`) and
populated inside `_load_file_once`'s existing per-line loop (append `row`
to `_all_records` there too, right next to the existing `_by_agent[agent] =
row` line). Rename the existing lazy-loader's guard so both accumulators
share one load pass — no separate `_load_all_records` function is needed;
reuse `_load_file_once()` for both `get_last_run` and `list_runs`/`get_run_by_id`
(fix the test above to call `_load_file_once()` conceptually — in practice
just call the existing loader).

- [ ] **Step 4: Add the routes**

In `src/masova_agent/main.py`, after the `GET /agents` route (Phase 1):

```python
@app.get("/agent/runs", dependencies=[Depends(require_scope("read:runs"))])
async def list_agent_runs(agent: Optional[str] = None, limit: int = 100):
    from .runtime import run_store

    return {
        "runs": run_store.list_runs(agent=agent, limit=limit),
        "chain_verified": run_store.verify_chain(),
    }


@app.get("/agent/runs/{run_id}", dependencies=[Depends(require_scope("read:runs"))])
async def get_agent_run(run_id: str):
    from .runtime import run_store

    rec = run_store.get_run_by_id(run_id)
    if not rec:
        raise HTTPException(status_code=404, detail="run not found")
    return rec
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_reasoning_trace.py -v`
Expected: PASS (8 tests total)

- [ ] **Step 6: Document the endpoints**

In `docs/AGENT_PLATFORM.md`, extend the "Agent registry" section (added in
Phase 1) with:

```markdown
`GET /agent/runs?agent=&limit=` and `GET /agent/runs/{run_id}` (trigger API
key) return persisted run records including each run's structured
`reasoning_trace` (per-tool-call name, args, result status, a truncated
summary of the actual data the tool returned, duration, timestamp) and a
`chain_verified` flag from the SHA-256 hash chain over `data/runs/runs.jsonl`.
This is the endpoint to cite in the demo when showing an agent's decision
traced back to real data — e.g. an inventory reorder proposal next to the
`list_low_stock` step that read the exact row driving it.
```

- [ ] **Step 7: Run the full test suite to check for regressions**

Run: `pytest tests/ -v --ignore=tests/test_scenarios.py`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/masova_agent/main.py src/masova_agent/runtime/run_store.py docs/AGENT_PLATFORM.md tests/test_reasoning_trace.py
git commit -m "feat: expose GET /agent/runs and /agent/runs/{run_id} with reasoning trace and chain verification"
```

---

## Self-Review Notes

- **Spec coverage:** structured step capture (Task 1), ops loop
  instrumentation (Task 2), chat path instrumentation (Task 3), hash chain
  (Task 4), new endpoint (Task 5), error handling (a raising tool call
  still records `result_status: "error"` — built into Task 2's
  instrumentation, not a separate task; chain verification never blocks
  reads — built into Task 5's route returning `chain_verified` as data,
  never raising).
- **Placeholder scan:** none found. Task 3's `duration_ms: 0.0` is called
  out explicitly as a real, documented limitation of the ADK event API,
  not a placeholder standing in for something achievable but skipped.
- **Type consistency:** `ToolCallStep` fields (`index`, `tool_name`,
  `args`, `result_status`, `result_summary`, `duration_ms`, `at`) match
  exactly across Task 1's dataclass, Task 2's and Task 3's raw-dict
  returns, and Task 1's `_extract_trace` conversion. `verify_chain(agent_name=None) -> bool`
  (Task 4) matches its usage in Task 5's route.
- **Added mid-plan:** `result_summary` was added to `ToolCallStep` after
  the user asked how the demo actually shows *where an agent's data comes
  from* — `result_status`/`duration_ms` alone only prove a tool ran, not
  what it saw. Task 3 additionally needed a `_backfill_result_summary`
  helper since ADK emits a function call and its result as separate
  events, unlike `ops_llm.py`'s loops which see both in one place.
