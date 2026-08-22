# Agent Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a live `GET /agents` catalog endpoint that derives every field from running code — the tool allowlists, the actual scheduler jobs, and a newly-persisted run-record store — with no static/hardcoded agent metadata beyond human display labels.

**Architecture:** A new `runtime/run_store.py` (mirrors `runtime/proposal_store.py`'s JSONL pattern) persists every `AgentRunResult`, called from inside `AuditLogger.log_run()`. A new `runtime/registry.py` reads `AGENT_ALLOWLISTS` (`wrap.py`), `policy.DEFAULT_TOOL_REGISTRY`, the live APScheduler jobs, and `run_store.get_last_run()` to build the catalog. `main.py` exposes it as `GET /agents`, gated by the existing `verify_trigger_api_key` dependency.

**Tech Stack:** Python 3.11, FastAPI, APScheduler, pytest.

**Spec:** `docs/superpowers/specs/2026-08-22-agent-registry-design.md`

## Global Constraints

- No hardcoded operational data — `schedule`, `trigger_type`, `tool_allowlist`, `last_run` must all be derived from live code/state at request time. Only `name` and `category` are hand-authored static display labels (explicitly allowed by the spec).
- No `version` field — inventing one with no real meaning behind it is exactly the hardcoding this project forbids.
- Auth: reuse `verify_trigger_api_key` (`auth.py`) as-is — Phase 2 replaces this later; do not build new auth here.
- Test import style matches the existing suite: `from masova_agent.x import y` (no `src.` prefix — `tests/conftest.py` inserts `src/` onto `sys.path`).

---

### Task 1: Persist run records (`runtime/run_store.py`)

**Files:**
- Create: `src/masova_agent/runtime/run_store.py`
- Modify: `src/masova_agent/runtime/audit.py:29-56` (`AuditLogger.log_run`)
- Test: `tests/test_run_store.py`

**Interfaces:**
- Consumes: `AgentRunResult.to_dict()` (`runtime/models.py:153-167`, already exists) — record shape it persists is whatever `AuditLogger.log_run` already builds as `record` (see `audit.py:38-51`).
- Produces: `record_run(record: dict) -> dict`, `get_last_run(agent_name: str) -> dict | None`, `clear_for_tests() -> None` — Task 2 and 3 depend on `get_last_run`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_run_store.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from masova_agent.runtime import run_store


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_DATA_DIR", str(tmp_path / "runs"))
    run_store.clear_for_tests()
    yield
    run_store.clear_for_tests()


def test_get_last_run_none_when_never_run():
    assert run_store.get_last_run("inventory_reorder") is None


def test_record_run_then_get_last_run_returns_it():
    rec = {
        "agent": "inventory_reorder",
        "status": "ok",
        "used_fallback": False,
        "at": "2026-08-22T10:00:00+00:00",
        "trigger_type": "scheduled",
    }
    run_store.record_run(rec)
    last = run_store.get_last_run("inventory_reorder")
    assert last["status"] == "ok"
    assert last["used_fallback"] is False


def test_record_run_persists_across_reload(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_DATA_DIR", str(tmp_path / "runs2"))
    run_store.clear_for_tests()
    run_store.record_run({"agent": "kitchen_coach", "status": "ok", "at": "t1"})
    run_store.clear_for_tests()  # simulate cold start — forces reload from file
    last = run_store.get_last_run("kitchen_coach")
    assert last is not None
    assert last["status"] == "ok"


def test_second_record_for_same_agent_overwrites_last():
    run_store.record_run({"agent": "dynamic_pricing", "status": "ok", "at": "t1"})
    run_store.record_run({"agent": "dynamic_pricing", "status": "error", "at": "t2"})
    last = run_store.get_last_run("dynamic_pricing")
    assert last["status"] == "error"
    assert last["at"] == "t2"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_run_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'masova_agent.runtime.run_store'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/masova_agent/runtime/run_store.py
"""
Durable last-run-per-agent storage (v1).

Primary: in-memory + append-only JSONL under data/runs/ (gitignored).
Mirrors runtime/proposal_store.py's pattern exactly — same lock, same
lazy-load-once, same "later lines win" reconciliation.

Feeds the Agent Registry's `last_run` field (see registry.py) and is the
foundation Phase 3 (reasoning-chain observability) extends with a
structured per-tool-call trace and hash chain — this module only tracks
the most recent record per agent, nothing more.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_by_agent: dict[str, dict[str, Any]] = {}
_loaded = False


def _data_dir() -> Path:
    root = os.getenv("RUN_DATA_DIR")
    if root:
        return Path(root)
    return Path(__file__).resolve().parents[3] / "data" / "runs"


def _jsonl_path() -> Path:
    return _data_dir() / "runs.jsonl"


def record_run(record: dict[str, Any]) -> dict[str, Any]:
    agent = str(record.get("agent") or record.get("agent_name") or "")
    if not agent:
        raise ValueError("record_run requires a non-empty 'agent' key")
    rec = dict(record)
    rec["agent"] = agent
    with _lock:
        _by_agent[agent] = rec
        try:
            d = _data_dir()
            d.mkdir(parents=True, exist_ok=True)
            with open(_jsonl_path(), "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, default=str) + "\n")
        except Exception as e:
            logger.warning("run record file append failed: %s", e)
    return rec


def get_last_run(agent_name: str) -> Optional[dict[str, Any]]:
    _load_file_once()
    with _lock:
        hit = _by_agent.get(agent_name)
        return dict(hit) if hit else None


def _load_file_once() -> None:
    global _loaded
    if _loaded:
        return
    path = _jsonl_path()
    if not path.exists():
        _loaded = True
        return
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                agent = row.get("agent")
                if not agent:
                    continue
                with _lock:
                    _by_agent[agent] = row  # later lines win
        _loaded = True
    except Exception as e:
        logger.warning("run record file load failed: %s", e)
        _loaded = True


def clear_for_tests() -> None:
    global _loaded
    with _lock:
        _by_agent.clear()
    _loaded = False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_run_store.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Wire `AuditLogger.log_run` to persist**

In `src/masova_agent/runtime/audit.py`, the `log_run` method already builds
a `record` dict (lines ~38-51) before redacting and logging it. Add the
persist call right after redaction, before returning:

```python
    def log_run(self, result: AgentRunResult) -> dict[str, Any]:
        proposal_summaries = [
            {
                "type": p.type,
                "summary": (p.summary or "")[:200],
                "rationale": (p.rationale or "")[:200],
                "store_id": p.store_id,
            }
            for p in result.proposals[:20]
        ]
        record = {
            "event": "agent_run",
            "run_id": result.run_id,
            "agent": result.agent_name,
            "trigger_type": result.trigger_type,
            "store_id": result.store_id,
            "status": result.status,
            "used_fallback": result.used_fallback,
            "tools_used": list(result.tools_used),
            "proposal_count": len(result.proposals),
            "proposal_types": [p.type for p in result.proposals],
            "proposal_summaries": proposal_summaries,
            "summary": (result.summary or "")[:500],
            "latency_ms": round(result.latency_ms, 2),
            "error": result.error,
        }
        record = self._redact(record)
        self.records.append(record)
        self._log.info("agent_audit %s", json.dumps(record, default=str))
        try:
            from . import run_store
            run_store.record_run(record)
        except Exception as e:
            self._log.warning("run_store persist failed: %s", e)
        return record
```

(The `try/except` here matches the resilience posture `proposal_store.py`
already uses for its own file writes — a persistence failure must never
break an agent run.)

- [ ] **Step 6: Add a test proving the wiring works end-to-end**

Append to `tests/test_run_store.py`:

```python
def test_audit_logger_persists_via_run_store(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_DATA_DIR", str(tmp_path / "runs3"))
    run_store.clear_for_tests()

    from masova_agent.runtime.audit import AuditLogger
    from masova_agent.runtime.models import AgentRunResult

    audit = AuditLogger()
    result = AgentRunResult(
        agent_name="shift_optimisation",
        trigger_type="scheduled",
        status="ok",
        used_fallback=False,
    )
    audit.log_run(result)

    last = run_store.get_last_run("shift_optimisation")
    assert last is not None
    assert last["status"] == "ok"
```

- [ ] **Step 7: Run the full test file and verify all pass**

Run: `pytest tests/test_run_store.py -v`
Expected: PASS (5 tests)

- [ ] **Step 8: Add `data/runs/` to `.gitignore`**

Check `.gitignore` already has `data/proposals/`; add `data/runs/` next to
it following the same pattern.

- [ ] **Step 9: Commit**

```bash
git add src/masova_agent/runtime/run_store.py src/masova_agent/runtime/audit.py tests/test_run_store.py .gitignore
git commit -m "feat: persist agent run records for registry status lookups"
```

---

### Task 2: Registry derivation module (`runtime/registry.py`)

**Files:**
- Create: `src/masova_agent/runtime/registry.py`
- Test: `tests/test_registry.py`

**Interfaces:**
- Consumes: `AGENT_ALLOWLISTS: dict[str, list[str]]` (`runtime/wrap.py:12`), `DEFAULT_TOOL_REGISTRY: dict[str, ToolRisk]` (`runtime/policy.py:16`), `get_scheduler()` (`scheduler/scheduler.py:18`), `run_store.get_last_run(agent_name: str) -> dict | None` (Task 1).
- Produces: `build_registry() -> list[dict]` — Task 3 (the FastAPI route) depends on this exact function name and return shape.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_registry.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'masova_agent.runtime.registry'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/masova_agent/runtime/registry.py
"""
Live agent catalog — every field derived from running code, never hardcoded.

Sources:
  - AGENT_ALLOWLISTS (wrap.py)        -> agent ids + tool allowlists
  - DEFAULT_TOOL_REGISTRY (policy.py) -> risk tier per tool
  - the live APScheduler jobs         -> trigger_type + schedule
  - run_store.get_last_run            -> last_run status

Only `name` and `category` below are hand-authored display metadata — they
have no live source to derive from and aren't operational data.
"""

from __future__ import annotations

from typing import Any, Optional

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .wrap import AGENT_ALLOWLISTS
from .policy import DEFAULT_TOOL_REGISTRY
from . import run_store

AGENT_LABELS: dict[str, tuple[str, str]] = {
    "support_chat": ("Support Chat", "chat"),
    "demand_forecast": ("Demand Forecast", "scheduled"),
    "inventory_reorder": ("Inventory Reorder", "scheduled"),
    "churn_prevention": ("Churn Prevention", "scheduled"),
    "review_response": ("Review Response", "event"),
    "shift_optimisation": ("Shift Optimisation", "scheduled"),
    "kitchen_coach": ("Kitchen Coach", "scheduled"),
    "dynamic_pricing": ("Dynamic Pricing", "scheduled"),
}

ENDPOINT_MAP: dict[str, str] = {
    "support_chat": "/agent/chat",
    "demand_forecast": "/agents/demand-forecast/trigger",
    "inventory_reorder": "/agents/inventory-reorder/trigger",
    "churn_prevention": "/agents/churn-prevention/trigger",
    "review_response": "/agents/review-response/trigger",
    "shift_optimisation": "/agents/shift-optimisation/trigger",
    "kitchen_coach": "/agents/kitchen-coach/trigger",
    "dynamic_pricing": "/agents/dynamic-pricing/trigger",
}

# Agents with no scheduler job at all — the schedule is structurally absent,
# not merely unregistered yet.
NO_SCHEDULER_JOB: dict[str, str] = {
    "support_chat": "chat",
    "review_response": "rabbitmq+manual",
}


def _describe_trigger(trigger: Any) -> tuple[str, str]:
    if isinstance(trigger, IntervalTrigger):
        total_seconds = trigger.interval.total_seconds()
        hours = total_seconds / 3600
        if hours == int(hours):
            return "interval", f"every {int(hours)}h"
        return "interval", f"every {int(total_seconds)}s"
    if isinstance(trigger, CronTrigger):
        parts = [
            f"{field.name}={field}"
            for field in trigger.fields
            if str(field) != "*"
        ]
        return "cron", ", ".join(parts)
    return "unknown", str(trigger)


def build_registry() -> list[dict]:
    from ..scheduler.scheduler import get_scheduler

    jobs_by_id = {job.id: job for job in get_scheduler().get_jobs()}

    entries: list[dict] = []
    for agent_id, tools in AGENT_ALLOWLISTS.items():
        name, category = AGENT_LABELS.get(agent_id, (agent_id, "scheduled"))

        if agent_id in NO_SCHEDULER_JOB:
            trigger_type: str = NO_SCHEDULER_JOB[agent_id]
            schedule: Optional[str] = None
        else:
            job = jobs_by_id.get(agent_id)
            if job is not None:
                trigger_type, schedule = _describe_trigger(job.trigger)
            else:
                trigger_type, schedule = "unknown", None

        allowlist = [
            {"name": t, "tier": DEFAULT_TOOL_REGISTRY[t].tier.value}
            for t in tools
            if t in DEFAULT_TOOL_REGISTRY
        ]

        entries.append({
            "id": agent_id,
            "name": name,
            "category": category,
            "trigger_type": trigger_type,
            "schedule": schedule,
            "tool_allowlist": allowlist,
            "last_run": run_store.get_last_run(agent_id),
            "endpoint": ENDPOINT_MAP.get(agent_id, ""),
        })
    return entries
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_registry.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add src/masova_agent/runtime/registry.py tests/test_registry.py
git commit -m "feat: derive agent registry catalog from live allowlists, scheduler, and run store"
```

---

### Task 3: `GET /agents` route

**Files:**
- Modify: `src/masova_agent/main.py` (add route after the existing `/agent/proposals` routes, ~line 232)
- Modify: `docs/AGENT_PLATFORM.md` (document the new endpoint)
- Test: `tests/test_registry.py` (append route-level tests)

**Interfaces:**
- Consumes: `build_registry()` (Task 2), `verify_trigger_api_key` (`auth.py`, already imported in `main.py`).
- Produces: `GET /agents` → `{"agents": [...]}`, consumed by nothing else in this repo (external consumer is the separate manager frontend, out of scope here).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_registry.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_registry.py -v -k test_get_agents`
Expected: FAIL with 404 (route doesn't exist yet)

- [ ] **Step 3: Add the route**

In `src/masova_agent/main.py`, immediately after the `resolve_action_proposal`
route (the last route defined in the file, ending around line 232), add:

```python
# ---------------------------------------------------------------------------
# Agent registry — live catalog of the fleet (Phase 1, Fortified Enterprise Fleet)
# ---------------------------------------------------------------------------

@app.get("/agents", dependencies=[Depends(verify_trigger_api_key)])
async def list_agents():
    """Live agent catalog — every field derived from running code, no static list."""
    from .runtime.registry import build_registry

    return {"agents": build_registry()}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_registry.py -v`
Expected: PASS (11 tests total)

- [ ] **Step 5: Document the endpoint**

In `docs/AGENT_PLATFORM.md`, add a new section after "## ActionProposal
closed loop" (before "## Out of scope"):

```markdown
## Agent registry

`GET /agents` (trigger API key) returns a live catalog of all 8 agents —
id, display name, category, trigger type, schedule, tool allowlist (with
risk tier), most recent run status, and trigger endpoint. Every field
except `name`/`category` is derived at request time from
`AGENT_ALLOWLISTS`, the live APScheduler jobs, and the persisted run-record
store (`runtime/run_store.py`) — nothing is hardcoded or cached stale.
```

- [ ] **Step 6: Run the full test suite to check for regressions**

Run: `pytest tests/ -v --ignore=tests/test_scenarios.py`
Expected: PASS, no regressions in existing routes/tests

- [ ] **Step 7: Commit**

```bash
git add src/masova_agent/main.py docs/AGENT_PLATFORM.md tests/test_registry.py
git commit -m "feat: expose GET /agents live registry endpoint"
```

---

## Self-Review Notes

- **Spec coverage:** Data flow (Task 2), persistence (Task 1), API contract
  (Task 3), error handling (registry falls back to `"unknown"`/`null`
  rather than raising when a scheduler job is missing — no separate task
  needed, it's built into Task 2's implementation), testing (all three
  tasks). No `version` field, confirmed by `test_no_version_field_present`.
- **Placeholder scan:** none found — every step has real code.
- **Type consistency:** `build_registry() -> list[dict]` (Task 2) is
  exactly what Task 3's route wraps in `{"agents": ...}`; `get_last_run`
  signature matches between Task 1's implementation and Task 2's usage.
