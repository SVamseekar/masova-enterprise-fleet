# Enterprise Fleet Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish every agent and copilot feature in one HITL loop: 7 specialists + Gemini voice in/out + approve-apply + memory + RAG + runtime robustness. Demo packaging (watch pulse, chain badge, Devpost extras) comes after that is green.

**Architecture:** Keep AgentRuntime + ops tools + DEMO SQLite. Add in-flight run records so the console harness tells the truth. Expand manager copilot tools. Apply remaining proposal types on Approve (including capped menu prices). Add lexical-fallback RAG. Do not rewrite the HITL runtime.

**Tech Stack:** Python 3.12, FastAPI, Google ADK, google-genai (Gemini 3.5 Flash + text-embedding-004 + optional Gemma), Redis, APScheduler, SQLite, vanilla `/console` HTML.

**Spec:** `docs/superpowers/specs/2026-08-29-enterprise-fleet-master-design.md`

## Global Constraints

- Product UI name: **MaSoVa AI**. Harness is the hero; chat is the mouth; Approve is the commit.
- `DEMO_MODE=true` is the submission runtime. No Dell LAN in source defaults, README, or e2e.
- Agents never EXECUTE. Manager Approve **applies** demo rows (PO, campaign, shifts, **capped price**, forecast, review copy, kitchen brief).
- Public story: Gemini + Google ADK only (never name a non-Google iteration provider in docs/UI/commits).
- CI tests must pass with `GEMMA_MODEL` unset and without a live LLM key.
- `store_id` unknown → that id only, never silent fleet fallthrough.
- Existing pytest suite stays green.
- **Voice:** Gemini STT in and Gemini TTS out. No `speechSynthesis`. No Celery, org RBAC, Grafana.
- **Gemma:** already in `guardrails.py`. Do not rebuild. Task 11 is verify + env only.

## Build phases (execute in this order)

**Phase A — agents and features (do first)**  
Tasks 1, 2, 4, 5, 6, 7, 8, 3B (Gemini TTS), 9, 10, 11, then Task 3 **without** watch pulse / chain badge (rail + live run only).

**Phase B — demo packaging (later)**  
Task 3 remainder (watch + SHA-256 pill), 12, 12B, 12C, 13.

## File map

| File | Role |
|------|------|
| `src/masova_agent/runtime/run_store.py` | `upsert_run`; `chain_report()` (verified, length, tip) |
| `src/masova_agent/runtime/agent_runtime.py` | Write `running` at start; stamp `request.run_id` |
| `src/masova_agent/runtime/ops_llm.py` | `upsert_run` after **each** tool in GenAI and scripted loops |
| `src/masova_agent/runtime/circuit.py` | Consecutive LLM-failure breaker (new) |
| `src/masova_agent/runtime/registry.py` | `next_run_time`, `in_flight`, `manager_chat` conductor |
| `src/masova_agent/runtime/policy.py` | Register new manager tools as READ/PROPOSE |
| `src/masova_agent/runtime/wrap.py` | `manager_chat` allowlist |
| `src/masova_agent/runtime/proposal_apply.py` | Price + forecast + review + kitchen apply |
| `src/masova_agent/agents/manager_chat_agent.py` | All 7 run_*; proposal tools; memory; RAG |
| `src/masova_agent/agents/*_agent.py` | `store_id` on remaining run_* |
| `src/masova_agent/main.py` | storeId on remaining triggers; rate limit; `GET /agent/watch`; seed-on-boot |
| `src/masova_agent/knowledge/rag.py` | Chunk, embed, search (new) |
| `data/knowledge/*.md` | SOP corpus (new) |
| `src/masova_agent/runtime/rate_limit.py` | Redis token bucket (new) |
| `docs/hackathon/masova-ai-console.html` | Live harness; rail; play Gemini `audioBase64`; no Support Chat |
| `src/masova_agent/agents/manager_chat_agent.py` | Also `synthesize_manager_reply` Gemini TTS |
| `tests/test_harness_inflight.py` | In-flight runs |
| `tests/test_manager_chat.py` | Tools, memory, approve |
| `tests/test_rag.py` | Lexical search |
| `tests/test_proposal_reject_apply.py` / apply tests | Price write |
| `tests/test_rate_limit.py` | 429 |
| `docs/CAPABILITY_MAP.md`, `README.md`, `docs/AGENT_PLATFORM.md` | Match product |
| `docs/hackathon/architecture-diagram.html` | Devpost architecture picture |
| `scripts/test-e2e.sh` | Local DEMO_MODE |
| `config/env.example` | `DEMO_WATCH_SEC`, `RATE_LIMIT_PER_MIN`, `GEMMA_MODEL`, `OPS_LLM_TIMEOUT_SEC` |

---

### Task 1: In-flight run records

**Files:**
- Modify: `src/masova_agent/runtime/run_store.py`
- Modify: `src/masova_agent/runtime/agent_runtime.py`
- Modify: `src/masova_agent/runtime/models.py` (`AgentRunRequest.run_id: Optional[str] = None`)
- Modify: `src/masova_agent/runtime/ops_llm.py`
- Test: `tests/test_harness_inflight.py`

**Interfaces:**
- Produces: `run_store.upsert_run(record: dict) -> dict` (no new hash chain link when `status=="running"`; final `record_run` still chains)
- Produces: `run_store.get_run_by_id` returns the running stub during the call
- Produces: `run_store.chain_report() -> dict` with `verified: bool`, `length: int`, `tip: str`
- Consumes: existing `record_run` for the terminal audit line
- `AgentRuntime.run` sets `request.run_id` before calling the LLM runner so `ops_llm` can upsert

- [x] **Step 1: Write the failing test**

```python
# tests/test_harness_inflight.py
import asyncio
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
    # Allow the runtime to persist the stub
    await asyncio.sleep(0.05)
    running = [r for r in run_store.list_runs(agent="inventory_reorder") if r.get("status") == "running"]
    assert running, "expected an in-flight running record"
    assert running[0].get("run_id")
    result = await task
    assert result.status == "ok"
    final = run_store.get_run_by_id(result.run_id)
    assert final["status"] == "ok"
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_harness_inflight.py::test_run_is_visible_as_running_before_fallback_finishes -v`  
Expected: FAIL (no running stub)

- [x] **Step 3: Implement `upsert_run` and start-of-run stub**

In `run_store.py` add `upsert_run` that updates an existing `run_id` in `_all_records` / `_by_agent` **without** advancing the hash chain when `status == "running"`. Terminal `record_run` from `AuditLogger` remains the chained event.

In `AgentRuntime.run`, immediately after minting `run_id`, set `request.run_id = run_id` and call `upsert_run` with `status="running"`, `agent`, `store_id`, `trigger_type`, empty `reasoning_trace`.

- [x] **Step 4: Mid-run upsert — failing test then implement**

```python
@pytest.mark.asyncio
async def test_scripted_loop_upserts_trace_after_each_tool(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_DATA_DIR", str(tmp_path))
    run_store.clear_for_tests()
    from masova_agent.runtime.ops_llm import run_scripted_tool_loop
    from masova_agent.runtime.models import AgentRunRequest

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
```

After each `invoke_tool` in `run_genai_tool_loop` **and** `run_scripted_tool_loop`, if `request.run_id`:

```python
from . import run_store
run_store.upsert_run({
    "run_id": request.run_id,
    "agent": request.agent_name,
    "status": "running",
    "store_id": request.store_id,
    "tools_used": tools_used,
    "reasoning_trace": list(trace),
})
```

Add `chain_report()` in the same task:

```python
def test_chain_report_counts_terminal_records_only(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_DATA_DIR", str(tmp_path))
    run_store.clear_for_tests()
    run_store.upsert_run({"run_id": "r1", "agent": "inventory_reorder", "status": "running"})
    run_store.record_run({"agent": "inventory_reorder", "run_id": "r1", "status": "ok"})
    report = run_store.chain_report()
    assert report["verified"] is True
    assert report["length"] == 1
    assert isinstance(report["tip"], str) and len(report["tip"]) >= 8
```

- [x] **Step 5: Run tests**

Run: `pytest tests/test_harness_inflight.py tests/test_run_store.py -q`  
Expected: PASS

- [x] **Step 6: Commit**

```bash
git add src/masova_agent/runtime/run_store.py src/masova_agent/runtime/agent_runtime.py src/masova_agent/runtime/ops_llm.py src/masova_agent/runtime/models.py tests/test_harness_inflight.py
git commit -m "feat(runtime): in-flight runs and mid-run tool upserts"
```

---

### Task 2: Registry next_run_time, in_flight, and conductor

**Files:**
- Modify: `src/masova_agent/runtime/wrap.py` (`AGENT_ALLOWLISTS["manager_chat"]`)
- Modify: `src/masova_agent/runtime/registry.py`
- Test: `tests/test_registry.py`

**Interfaces:**
- Consumes: APScheduler `job.next_run_time`; `run_store.list_runs` status running
- Produces: each catalog entry `{ ..., "next_run_time": iso|null, "in_flight": dict|null }`
- Produces: `manager_chat` row: `name="Regional Manager Copilot"`, `category="conductor"`, `trigger_type="chat"`, `endpoint="/agent/manager/chat"`, `tool_allowlist` from `AGENT_ALLOWLISTS["manager_chat"]`
- Console still hides `support_chat`; catalog may keep it for the hidden diner API

- [x] **Step 1: Write failing assertions in `tests/test_registry.py`**

```python
def test_registry_includes_next_run_and_inflight_keys():
    from masova_agent.runtime.registry import build_registry
    entries = build_registry()
    inv = next(e for e in entries if e["id"] == "inventory_reorder")
    assert "next_run_time" in inv
    assert "in_flight" in inv

def test_registry_includes_manager_chat_conductor():
    from masova_agent.runtime.registry import build_registry
    entries = {e["id"]: e for e in build_registry()}
    copilot = entries["manager_chat"]
    assert copilot["category"] == "conductor"
    assert copilot["endpoint"] == "/agent/manager/chat"
    assert copilot["trigger_type"] == "chat"
    names = {t["name"] for t in copilot["tool_allowlist"]}
    assert "run_inventory_reorder" in names or len(copilot["tool_allowlist"]) >= 2
```

Change `test_registry_returns_exactly_the_eight_agent_ids` to `test_registry_ids_match_allowlists`: `ids == set(AGENT_ALLOWLISTS.keys())` and `"manager_chat" in ids`. `test_agent_maps_are_pinned_together` already requires LABEL/ENDPOINT/ALLOWLIST key equality — add `manager_chat` to **all three** in the same commit (`AGENT_LABELS`, `ENDPOINT_MAP`, `NO_SCHEDULER_JOB`).

- [x] **Step 2: Implement labels / NO_SCHEDULER_JOB / ENDPOINT_MAP / allowlist stub** (full tool list filled in Task 4; stub may be `list_stores` + `run_inventory_reorder` until then)

`build_registry`: `next_run_time` from `job.next_run_time.isoformat()`; `in_flight` = newest `status=="running"` run for that agent.

- [x] **Step 3: Run `pytest tests/test_registry.py -q` — PASS, then commit**

```bash
git commit -m "feat(registry): next_run_time, in_flight, manager_chat conductor"
```

---

### Task 3: Console live harness, watch pulse, chain badge

**Files:**
- Modify: `docs/hackathon/masova-ai-console.html`
- Modify: `src/masova_agent/main.py` (`GET /agent/watch`, extend `GET /agent/runs` with `chain_length` + `chain_tip`)
- Modify: `src/masova_agent/runtime/run_store.py` (`chain_report`)
- Test: `tests/test_console_masova_ai.py`, `tests/test_console.py`

**Interfaces:**
- Consumes: `GET /agents` `next_run_time` / `in_flight`; `GET /agent/runs?storeId=`; `GET /agent/watch?storeId=`
- Produces (Phase A): harness poll; conductor + 7 rail; click-to-run.  
- Produces (Phase B): watch pulse + SHA-256 pill.

- [x] **Step 1: Failing HTML + API tests** (Phase A harness asserts)

```python
def test_console_polls_harness_watch_and_chain_badge():
    html = open("docs/hackathon/masova-ai-console.html", encoding="utf-8").read()
    assert "setInterval" in html
    assert "in_flight" in html
    assert "next_run_time" in html
    # Phase A: live harness. Watch/chain HTML asserts belong in Phase B.

def test_render_agent_rail_skips_support_chat():
    html = open("docs/hackathon/masova-ai-console.html", encoding="utf-8").read()
    assert "if (agent.id === 'support_chat') continue" in html or 'agent.id !== "support_chat"' in html
```

- [ ] **Step 2 (Phase B): `GET /agent/watch` + inject `data-watch-sec`**

```python
def test_watch_endpoint_returns_counts(client, demo_env):
    r = client.get("/agent/watch", params={"storeId": demo_env["store_id"]}, headers=demo_env["headers"])
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["active_orders"], int)
    assert isinstance(body["kitchen_queue"], int)
    assert isinstance(body["pending_proposals"], int)
```

`require_scope("read:runs")`. Implementation: `count_active_orders` + kitchen CSV count + `proposal_store.list_proposals(status=PENDING, store_id=...)`. **No proposals minted.**

`serve_console` injects `data-watch-sec="{int(os.getenv('DEMO_WATCH_SEC', '20'))}"` next to the demo key. `config/env.example` documents `DEMO_WATCH_SEC=20`.

`GET /agent/runs` already returns `chain_verified`. Add:

```python
report = run_store.chain_report()  # {verified, length, tip}
return {"runs": ..., "chain_verified": report["verified"], "chain_length": report["length"], "chain_tip": report["tip"]}
```

- [x] **Step 3: Console** (Phase A: conductor+7, skip support_chat, poll, no watch/badge)

- Replace the **static** `#rail-team` HTML (it currently hardcodes `support_chat` first) with a conductor + 7 specialist skeleton, or an empty host that JS always fills. `renderAgentRailItem`: skip `support_chat`; sort `category === 'conductor'` first.
- Click specialist summary → `triggerAgentFromChip`. Click `manager_chat` → `composer-input.focus()`.
- Phase A: no watch timer, no chain pill yet. Pause harness interval when `document.hidden`.
- Do **not** invent kg/L. Do **not** add Open-Meteo. Do **not** use `speechSynthesis`.

- [x] **Step 4: `pytest tests/test_console_masova_ai.py tests/test_console.py -q` — PASS**

- [x] **Step 5: Commit** `feat(console): live harness and rail-click run`

- [ ] **Step 6 (Phase B only):** Add `GET /agent/watch`, `data-watch-sec`, `#chain-badge`, `#pulse-strip` as previously specified. Separate commit `feat(console): watch pulse and SHA-256 badge`.

---

### Task 3B: Gemini TTS out (same stack as STT)

**Files:**
- Modify: `src/masova_agent/agents/manager_chat_agent.py`
- Modify: `docs/hackathon/masova-ai-console.html`
- Modify: `config/env.example` (`GEMINI_TTS_MODEL`)
- Test: `tests/test_manager_chat.py`, `tests/test_console_masova_ai.py`

**Interfaces:**
- Produces: `async def synthesize_manager_reply(text: str) -> dict` → `{ "audioBase64": str, "mimeType": "audio/mp3" }` using `google.genai` and `GEMINI_TTS_MODEL` (fallback `LLM_MODEL` if that model accepts audio). Same `LLM_API_KEY`.
- `run_manager_chat` after screening the text reply: try TTS; on failure omit audio fields.
- Response already has `reply`; add `audioBase64`, `mimeType`.
- Console: if `data.audioBase64`, `new Audio("data:" + mime + ";base64," + data.audioBase64).play()`. Never `speechSynthesis`.

- [x] **Step 1: Failing tests**

```python
@pytest.mark.asyncio
async def test_manager_chat_attaches_gemini_tts_when_stubbed(monkeypatch):
    async def fake_tts(text: str) -> dict:
        return {"audioBase64": "AAAA", "mimeType": "audio/mp3"}
    monkeypatch.setattr(
        "masova_agent.agents.manager_chat_agent.synthesize_manager_reply",
        fake_tts,
    )
    async def fake_run(*args, **kwargs):
        return {"reply": "Stock is low.", "summary": "ok", "_runtime": {}}
    monkeypatch.setattr("masova_agent.runtime.wrap.run_ops_agent", fake_run)
    monkeypatch.setenv("DEMO_MODE", "true")
    from masova_agent.agents.manager_chat_agent import run_manager_chat
    out = await run_manager_chat("check stock", session_id="s", store_id="st")
    assert out["reply"]
    assert out.get("audioBase64") == "AAAA"

@pytest.mark.asyncio
async def test_manager_chat_text_survives_tts_failure(monkeypatch):
    async def boom(text: str):
        raise RuntimeError("tts_down")
    monkeypatch.setattr(
        "masova_agent.agents.manager_chat_agent.synthesize_manager_reply",
        boom,
    )
    async def fake_run(*args, **kwargs):
        return {"reply": "Stock is low.", "summary": "ok", "_runtime": {}}
    monkeypatch.setattr("masova_agent.runtime.wrap.run_ops_agent", fake_run)
    from masova_agent.agents.manager_chat_agent import run_manager_chat
    out = await run_manager_chat("check stock", session_id="s", store_id="st")
    assert out["reply"] == "Stock is low."
    assert not out.get("audioBase64")

def test_console_plays_gemini_audio_not_speech_synthesis():
    html = open("docs/hackathon/masova-ai-console.html", encoding="utf-8").read()
    assert "audioBase64" in html
    assert "speechSynthesis" not in html
```

- [x] **Step 2: Implement `synthesize_manager_reply` via `google.genai` audio generation.** If the SDK returns inline bytes, base64-encode them. Timeout with `OPS_LLM_TIMEOUT_SEC`. Never raise out of `run_manager_chat`. (`config/env.example` left to Lane A / docs task — getenv default in code.)

- [x] **Step 3: Tests PASS, commit** `feat(manager): Gemini TTS on copilot replies`

---

### Task 4: storeId on remaining agents + all 7 chat bindings

**Files:**
- Modify: `src/masova_agent/agents/demand_forecasting_agent.py`
- Modify: `src/masova_agent/agents/churn_prevention_agent.py`
- Modify: `src/masova_agent/agents/shift_optimisation_agent.py`
- Modify: `src/masova_agent/agents/kitchen_coach_agent.py`
- Modify: `src/masova_agent/agents/review_response_agent.py`
- Modify: `src/masova_agent/agents/manager_chat_agent.py`
- Modify: `src/masova_agent/runtime/wrap.py` (`manager_chat` allowlist)
- Modify: `src/masova_agent/runtime/policy.py`
- Modify: `src/masova_agent/main.py` trigger bodies
- Test: `tests/test_manager_chat.py`

**Interfaces:**
- Produces: `async def run_demand_forecast(store_id: Optional[str] = None)` (and churn, shift, kitchen) using `focus_store_list` like inventory
- Produces: manager tools `run_demand_forecast`, `run_churn_prevention`, `run_shift_optimisation`, `run_kitchen_coach`, `run_review_response`
- `run_review_response` loads latest rating≤3 review for the store from demo/ops if body omitted

- [x] **Step 1: Failing test** (Lane B: MANAGER_TOOLS)

```python
def test_manager_tools_include_all_seven_specialists():
    from masova_agent.agents.manager_chat_agent import MANAGER_TOOLS
    for name in (
        "run_inventory_reorder", "run_dynamic_pricing", "run_demand_forecast",
        "run_churn_prevention", "run_shift_optimisation", "run_kitchen_coach",
        "run_review_response",
    ):
        assert name in MANAGER_TOOLS
```

- [x] **Step 2: Implement signatures, HTTP `{storeId}`, manager wrappers, policy PROPOSE for `run_*` tools, wrap allowlist** (Lane B: manager wrappers + policy only; specialists/HTTP/wrap = Lane A)

HTTP bodies `{storeId}` on: `/agents/demand-forecast/trigger`, `/agents/churn-prevention/trigger`, `/agents/shift-optimisation/trigger`, `/agents/kitchen-coach/trigger` (inventory and pricing already accept it). Review trigger already takes a JSON body; pass `storeId` through.

Update `tests/test_equal_agent_quality.py` so the allowlist loop **also** includes `"manager_chat"`.

Keep `AGENT_ALLOWLISTS["manager_chat"]` and `MANAGER_TOOLS` as the **same list object or equal lists**. Later tasks (5, 8, 10) **append** names to both — never replace one and leave the other.

Add:

```python
def test_manager_allowlist_matches_manager_tools():
    from masova_agent.runtime.wrap import AGENT_ALLOWLISTS
    from masova_agent.agents.manager_chat_agent import MANAGER_TOOLS
    assert list(AGENT_ALLOWLISTS["manager_chat"]) == list(MANAGER_TOOLS)
```

Each wrapper:

```python
async def run_demand_forecast_tool(store_id: str = "") -> dict:
    from .demand_forecasting_agent import run_demand_forecast
    return await run_demand_forecast(store_id=store_id or None)
```

Register in `policy.DEFAULT_TOOL_REGISTRY` as `RiskTier.PROPOSE` (nested specialist may mint drafts).

- [x] **Step 3: `pytest tests/test_manager_chat.py` — PASS** (skipped `test_equal_agent_quality.py`: requires wrap.py manager_chat allowlist — Lane A)

- [x] **Step 4: Commit** `feat(manager): bind all seven specialists with storeId`

---

### Task 5: In-chat proposal list / approve / reject

**Files:**
- Modify: `src/masova_agent/agents/manager_chat_agent.py`
- Modify: `src/masova_agent/runtime/policy.py`
- Modify: `src/masova_agent/tools/ops_tools.py` (or new `src/masova_agent/tools/proposal_tools.py`)
- Test: `tests/test_manager_chat.py`

**Interfaces:**
- Produces: `async def list_pending_proposals(store_id: str = "") -> dict`
- Produces: `async def approve_proposal(proposal_id: str, note: str = "") -> dict`
- Produces: `async def reject_proposal(proposal_id: str, note: str = "") -> dict`
- These call `proposal_store` + `apply_approved_proposal` / `apply_rejected_proposal` — **same path as** `POST /agent/proposals/{id}/resolve`

- [x] **Step 1: Failing tests**

```python
@pytest.mark.asyncio
async def test_approve_proposal_tool_applies_like_http(monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("PROPOSAL_DATA_DIR", str(tmp_path))
    from masova_agent.runtime import proposal_store
    from masova_agent.agents.manager_chat_agent import approve_proposal, list_pending_proposals
    rec = proposal_store.save_proposal({
        "proposal_id": "p1", "agent": "inventory_reorder", "type": "DRAFT_PURCHASE_ORDER",
        "store_id": "s1", "status": "PENDING", "summary": "draft po",
        "requires_approval": True, "payload": {},
    })
    listed = await list_pending_proposals(store_id="s1")
    assert any(p.get("proposal_id") == rec["proposal_id"] for p in listed.get("proposals", []))
    out = await approve_proposal(rec["proposal_id"])
    assert out.get("status") == "APPROVED" or out.get("ok") is True
```

- [x] **Step 2: Implement tools, append to `MANAGER_TOOLS` **and** `AGENT_ALLOWLISTS["manager_chat"]`, schemas, policy READ for list / PROPOSE for approve/reject**

Approve/reject must check the proposal exists and is PENDING; 400-equivalent `{ok:False,error:...}` otherwise. Never EXECUTE.

- [x] **Step 3: Tests PASS, commit** `feat(manager): in-chat proposal list approve reject`

---

### Task 6: Apply-on-approve for prices and remaining types

**Files:**
- Modify: `src/masova_agent/runtime/proposal_apply.py`
- Modify: `src/masova_agent/main.py` (`DEMO_TABLE_ALLOWLIST` add `campaigns`, `staff_shifts` if missing)
- Test: `tests/test_proposal_reject_apply.py` (or new `tests/test_proposal_apply_price.py`)

**Interfaces:**
- Produces: `SUGGEST_PRICE_ADJUSTMENT` Approve updates `menu_items.price` for each id in `payload["item_ids"]` using `payload["percent"]` and `payload["direction"]` (`increase` → `price * (1 + pct/100)`, `discount` → `price * (1 - pct/100)`). Re-cap with `PRICE_INCREASE_PCT_MAX` (12) and `PRICE_DISCOUNT_PCT_MAX` (15). Reject never touches price.
- `WRITE_FORECAST`, `DRAFT_REVIEW_REPLY`, `DRAFT_KITCHEN_BRIEF` → INSERT into new demo table `manager_actions(id, store_id, type, status, payload_json, created_at)`. Add that table to `DEMO_TABLE_ALLOWLIST` as `manager_actions`.

- [x] **Step 1: Failing test**

```python
def test_approve_price_suggestion_writes_capped_menu_price(seeded_db, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    from masova_agent.runtime.proposal_apply import apply_approved_proposal
    from masova_agent.services.demo_backend import _connect
    conn = _connect()
    row = conn.execute("SELECT id, price FROM menu_items LIMIT 1").fetchone()
    before = row["price"]
    ok = apply_approved_proposal({
        "type": "SUGGEST_PRICE_ADJUSTMENT",
        "store_id": "any",
        "payload": {"item_ids": [row["id"]], "percent": 10, "direction": "increase"},
    })
    assert ok is True
    after = conn.execute("SELECT price FROM menu_items WHERE id=?", (row["id"],)).fetchone()["price"]
    assert after != before
```

Inspect `propose_price_suggestion` payload keys first and match them exactly in the apply function.

- [x] **Step 2: Implement apply; extend `storeProof()` to also GET `campaigns`, `staff_shifts`, `manager_actions` for the focus store (empty-safe).**

- [x] **Step 3: Tests PASS, commit** `feat(hitl): apply capped prices and remaining drafts on approve`

---

### Task 7: Multi-turn manager memory

**Files:**
- Modify: `src/masova_agent/agents/manager_chat_agent.py`
- Modify: `src/masova_agent/runtime/ops_llm.py` (`make_ops_llm_runner` accept `history: list[dict]`)
- Test: `tests/test_manager_chat.py`

**Interfaces:**
- Consumes: `RedisSessionService.get_session` / `append_turn` already used by `/agent/chat`
- Produces: `run_manager_chat` loads last 10 turns for `session_id`, passes as Gemini contents, appends user+assistant after the run

- [x] **Step 1: Failing test with in-memory session**

```python
@pytest.mark.asyncio
async def test_manager_chat_passes_prior_turns_to_runner(monkeypatch):
    captured = {}
    async def fake_run(*args, **kwargs):
        captured["context"] = kwargs.get("context")
        return {"reply": "ok", "summary": "ok", "_runtime": {}}
    monkeypatch.setattr("masova_agent.runtime.wrap.run_ops_agent", fake_run)
    monkeypatch.setenv("DEMO_MODE", "true")
    from masova_agent.core.redis_session_service import RedisSessionService
    # Use fallback by pointing at a dead redis
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/1")
    from masova_agent.agents import manager_chat_agent as m
    await m.run_manager_chat("hello", session_id="s1", store_id="st")
    await m.run_manager_chat("and stock?", session_id="s1", store_id="st")
    hist = (captured.get("context") or {}).get("history") or []
    assert any("hello" in str(t) for t in hist)
```

Wire history through `context["history"]` into `make_ops_llm_runner` contents. If Redis is down, keep a process-local dict `_MANAGER_TURNS[session_id]` so demo Cloud Run (single instance, Redis optional) still remembers the thread.

- [x] **Step 2: Implement (manager_chat history + process-local; ops_llm contents hook = Lane A), tests PASS, commit** `feat(manager): multi-turn working memory`

---

### Task 8: Operations RAG engine

**Files:**
- Create: `data/knowledge/food_safety_haccp.md`
- Create: `data/knowledge/equipment_troubleshooting.md`
- Create: `data/knowledge/labor_compliance_eu.md`
- Create: `data/knowledge/supplier_slas.md`
- Create: `src/masova_agent/knowledge/__init__.py`
- Create: `src/masova_agent/knowledge/rag.py`
- Modify: `src/masova_agent/agents/manager_chat_agent.py`
- Modify: `src/masova_agent/runtime/policy.py` (`search_ops_manual` READ)
- Modify: `Dockerfile` COPY `data/knowledge/`
- Test: `tests/test_rag.py`

**Interfaces:**
- Produces: `async def search_ops_manual(query: str, category: str = "") -> dict`
- CI: lexical overlap, no network
- Live: `text-embedding-004` when `LLM_API_KEY` set; cache embeddings next to chunks

- [x] **Step 1: Write corpus files (Paris/EU restaurant ops, no live stock numbers)**

`food_safety_haccp.md` must contain a section on cooler temperatures so the golden query hits.

- [x] **Step 2: Failing test**

```python
@pytest.mark.asyncio
async def test_search_ops_manual_hits_haccp_cooler(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    from masova_agent.knowledge.rag import search_ops_manual
    out = await search_ops_manual("cooler temperature")
    assert out["ok"] is True
    blob = " ".join(h["text"] for h in out["hits"]).lower()
    assert "cooler" in blob or "celsius" in blob or "temp" in blob
```

- [x] **Step 3: Implement chunker + lexical search; optional embed path behind key; append `search_ops_manual` to `MANAGER_TOOLS` and `AGENT_ALLOWLISTS["manager_chat"]`; policy READ**

- [x] **Step 4: Tests PASS, commit** `feat(rag): ops manual search with lexical CI fallback`

---

### Task 9: Rate limit and LLM circuit breaker

**Files:**
- Create: `src/masova_agent/runtime/rate_limit.py`
- Create: `src/masova_agent/runtime/circuit.py`
- Modify: `src/masova_agent/main.py` (middleware)
- Modify: `src/masova_agent/runtime/agent_runtime.py`
- Test: `tests/test_rate_limit.py`, `tests/test_runtime.py`

**Interfaces:**
- `await check_rate_limit(key: str) -> bool`  (False → 429)
- `circuit.record_failure(agent: str)`; `circuit.allow_llm(agent: str) -> bool`
- Env: `RATE_LIMIT_PER_MIN` default 60; skip `/health` and `/console`

- [x] **Step 1: Failing tests**

```python
def test_rate_limit_blocks_after_budget(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "2")
    from masova_agent.runtime.rate_limit import reset_for_tests, check_rate_limit_sync
    reset_for_tests()
    assert check_rate_limit_sync("k") is True
    assert check_rate_limit_sync("k") is True
    assert check_rate_limit_sync("k") is False

def test_circuit_opens_after_three_llm_failures():
    from masova_agent.runtime.circuit import reset_for_tests, record_failure, allow_llm
    reset_for_tests()
    assert allow_llm("inventory_reorder") is True
    record_failure("inventory_reorder")
    record_failure("inventory_reorder")
    record_failure("inventory_reorder")
    assert allow_llm("inventory_reorder") is False
```

In-process counters are enough (Cloud Run max 1 instance). Optionally mirror to Redis like idempotency.

`AgentRuntime`: if `prefer_llm` and not `allow_llm(agent)`, skip LLM and use fallback; `record_failure` on `llm_failed`; `record_success` on LLM ok.

Also wrap `client.models.generate_content` in `run_genai_tool_loop` with `asyncio.wait_for(..., timeout=int(os.getenv("OPS_LLM_TIMEOUT_SEC", "45")))`. On timeout: raise so AgentRuntime falls back. `config/env.example`: `RATE_LIMIT_PER_MIN=60`.

- [x] **Step 2: Implement, PASS, commit** `feat(prod): rate limit, llm circuit breaker, generate timeout`

---

### Task 10: Fleet compare tool

**Files:**
- Modify: `src/masova_agent/tools/ops_tools.py`
- Modify: `src/masova_agent/agents/manager_chat_agent.py`
- Test: `tests/test_ops_llm_tools.py`

**Interfaces:**
- `async def compare_store_performance(store_id: str) -> dict` — READ; uses `read_order_metrics` / `read_kitchen_metrics` / `list_low_stock` for focus vs a small sample of other stores; **no LLM math**

- [x] **Step 1: Failing test**

```python
@pytest.mark.asyncio
async def test_compare_store_performance_has_store_and_fleet(monkeypatch):
    from masova_agent.tools import ops_tools
    async def fake_metrics(store_id=""):
        return {"ok": True, "active": 3 if store_id == "s1" else 1}
    monkeypatch.setattr(ops_tools, "read_order_metrics", fake_metrics)
    monkeypatch.setattr(ops_tools, "read_kitchen_metrics", fake_metrics)
    monkeypatch.setattr(ops_tools, "list_low_stock", fake_metrics)
    monkeypatch.setattr(ops_tools, "list_stores", lambda: {"ok": True, "stores": [{"id": "s1"}, {"id": "s2"}]})
    out = await ops_tools.compare_store_performance("s1")
    assert "store" in out and "fleet" in out
```

Append `"compare_store_performance"` to **both** `MANAGER_TOOLS` and `AGENT_ALLOWLISTS["manager_chat"]`. Policy READ.

- [x] **Step 2: Implement, tests PASS, commit** `feat(ops): compare_store_performance read tool`

---

### Task 11: Gemma bonus verification + env

**Files:**
- Modify: `config/env.example` (document `GEMMA_MODEL=gemma-3-12b-it` as Cloud Run bonus)
- Modify: `docs/CAPABILITY_MAP.md` (guardrails row)
- Test: `tests/test_guardrails.py` already covers hooks — run them

- [x] **Step 1: Confirm `screen_input` is used on manager chat (already) and customer chat**

- [ ] **Step 2: Add a console/README line: bonus Gemma classifier when `GEMMA_MODEL` is set; regex always on**

- [ ] **Step 3: `pytest tests/test_guardrails.py -q` PASS, commit** `docs(guardrails): document Gemma bonus for Cloud Run`

---

### Task 12: Product docs, hygiene, e2e, Cloud Run image

**Files:**
- Modify: `README.md`, `docs/AGENT_PLATFORM.md`, `docs/CAPABILITY_MAP.md`
- Modify: `scripts/test-e2e.sh`
- Modify: `Dockerfile` — COPY `data/knowledge/` (seed script already copied)
- Modify: `src/masova_agent/scheduler/scheduler.py` comments IST → Paris / `SCHEDULER_TZ`
- Delete: `src/masova_agent/data/models.py`, `src/masova_agent/data/repositories.py`, `src/masova_agent/services/customer_service.py`, `src/masova_agent/services/order_service.py`, `src/masova_agent/services/location_service.py`, `src/masova_agent/tools/system_briefing.py`
- Modify: `src/masova_agent/data/__init__.py`, `src/masova_agent/services/__init__.py`, `src/masova_agent/tools/__init__.py` (drop dead exports)
- Modify: `tests/test_regression.py` — remove `TestRepositorySaveKeyCollision` (it only exists for the mock repos)
- Move: `docs/ARCHITECTURE.md`, `docs/PROJECT_PHASES.md` → `docs/archive/`

**Interfaces:** none — narrative and image contents match the spec. Lifespan already seeds if SQLite is missing (`main.py`); this task **verifies** Dockerfile includes `scripts/seed_demo_data.py` and `data/knowledge/`.

- [ ] **Step 1: Failing test that dead modules are gone**

```python
# tests/test_hygiene.py
import importlib
import pytest

@pytest.mark.parametrize("mod", [
    "masova_agent.data.models",
    "masova_agent.services.customer_service",
    "masova_agent.tools.system_briefing",
])
def test_dead_modules_removed(mod):
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(mod)
```

Also assert `Dockerfile` text contains `data/knowledge` and `seed_demo_data.py`.

- [ ] **Step 2: Delete dead path, fix imports, IST comments, README hero = conductor + 7 + HITL apply + Cloud Run. Diner chat one line under “Not this product.”**

- [ ] **Step 3: `scripts/test-e2e.sh` uses localhost + `X-Agent-Api-Key` + DEMO_MODE; no `192.168.50.88`.**

- [ ] **Step 4:** `pytest tests/test_hygiene.py tests/ -q --ignore=...` full suite green.

- [ ] **Step 5: Commit** `chore: drop dead mock path and align docs to manager harness`

Cloud Run deploy remains an operator step from `docs/superpowers/specs/2026-08-22-ship-deployment-runbook.md`: `gemini-3.5-flash`, `DEMO_MODE=true`, `--max-instances=1`, Secret Manager for `LLM_API_KEY`, `JWT_SECRET`, `AGENT_API_KEYS`/`AGENT_TRIGGER_API_KEY`, `AGENT_TOKEN`. Do not claim deployed until `gcloud run deploy` has been run.

---

### Task 12B: Devpost architecture diagram

**Files:**
- Create: `docs/hackathon/architecture-diagram.html` (1400×900, same visual language as `/console`: dark, amber)
- Optional capture: `docs/hackathon/architecture-diagram.png`

**Interfaces:** Static artifact. Must show: Manager browser `/console` → FastAPI on Cloud Run (Gemini 3.5 Flash + Google ADK + 7 specialists + copilot + HITL) → Paris SQLite. Label SHA-256 ledger and Approve-apply. No LAN IPs. No non-Google iteration providers.

- [ ] **Step 1: Author the HTML board (three columns: Console / This service / Demo data).** Reuse the structure of `tmp/system-pictures.html` `#board-arch`, but add **Regional Manager Copilot** and **SHA-256 ledger**.

- [ ] **Step 2: Capture PNG** (Playwright or the browser-automation skill at 1400×900). Check the PNG into `docs/hackathon/` so Devpost can upload it.

- [ ] **Step 3: Commit** `docs: Devpost architecture diagram for Gemini ADK Cloud Run`

---

### Task 12C: Devpost bonus (operator — not application code)

- [ ] Public write-up (README section or blog) that states the project was built for the **All Things Agentic Hackathon**.
- [ ] Social post with `#AllThingsAgenticHackathon`.
- [ ] Cloud Run env `GEMMA_MODEL=gemma-3-12b-it` (or current Gemma id) so the bonus classifier is actually on in the video if credits allow.

---

### Task 13: Full verification

- [ ] **Step 1:** `pytest tests/ -q` — expected: PASS  
- [ ] **Step 2:** `/console` inventory rail click → harness **Running** with a tool name **during** the run → Approve → store proof PO changed  
- [ ] **Step 3:** Watch pulse: `#pulse-strip` or harness dots change within ~20s without a click  
- [ ] **Step 4:** Header chain pill green with a tip prefix  
- [ ] **Step 5:** Mic: speak a line → transcript in thread → **spoken** reply  
- [ ] **Step 6:** Rail has copilot + 7, no Support Chat  
- [ ] **Step 7:** Chat: “what does HACCP say about coolers?” hits RAG; “approve that PO” uses `approve_proposal`

---

## Spec coverage checklist

| Spec section | Task |
|---|---|
| In-flight harness + mid-run upserts | 1 |
| Registry next_run / in_flight / conductor | 2 |
| Live harness, watch pulse, SHA-256 badge | 3 |
| Gemini TTS out + Gemini STT in | 3B |
| All 7 specialists + storeId | 4 |
| In-chat approve | 5 |
| Apply including prices | 6 |
| Multi-turn memory | 7 |
| RAG corpus + search_ops_manual | 8 |
| Rate limit + circuit | 9 |
| compare_store_performance | 10 |
| Gemma bonus | 11 |
| Docs, hygiene, e2e, Dockerfile knowledge/seed | 12 |
| Devpost architecture diagram | 12B |
| Write-up + social + Gemma on Cloud Run | 12C |
| Golden evals / pytest | 13 |
| `OPS_LLM_TIMEOUT_SEC` | 9 |
| Price payload `item_ids`/`percent`/`direction` | 6 |
| `manager_actions` table | 6 |
| `MANAGER_TOOLS` == wrap allowlist | 4, 5, 8, 10 |
| Gemini Live / Celery / org RBAC / OTel SaaS / old masova-voice | Explicitly out (spec §8, §14) |

## Placeholder scan

Voice in/out is Gemini (Task 3B). Watch/badge/diagram are Phase B. Gemma is verify-only (already coded). No Celery, org RBAC, Grafana.
