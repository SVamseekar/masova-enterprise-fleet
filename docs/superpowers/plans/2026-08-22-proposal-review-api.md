# Proposal Review API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the two real gaps found in this repo's already-implemented `GET /agent/proposals` / `POST /agent/proposals/{id}/resolve` API — a `type` filter and an automatic sweep for stale `PENDING` proposals into `EXPIRED` — so the API is genuinely complete for the separate manager-frontend repo to build its approve/reject panel against.

**Architecture:** `proposal_store.list_proposals` gains a `type` filter parameter (it already filters by `store_id`/`status`/`agent`, this is one more of the same shape). A new `runtime/proposal_expiry.py::sweep_expired()` walks pending proposals and resolves stale ones to `EXPIRED`, registered as a daily APScheduler job.

**Tech Stack:** Python 3.11, FastAPI, APScheduler.

**Spec:** `docs/superpowers/specs/2026-08-22-proposal-review-api-design.md`

## Global Constraints

- `resolve_action_proposal` must continue rejecting `EXPIRED` as a client-submitted status — it stays system-only, set only by the sweep job.
- No hardcoding: the sweep threshold (72h) is a named constant, not a magic number scattered across the code; the sweep queries real persisted proposals, never a fabricated list.
- Test import style: `from masova_agent.x import y`.

---

### Task 1: `type` filter on `GET /agent/proposals`

**Files:**
- Modify: `src/masova_agent/runtime/proposal_store.py:71-88` (`list_proposals`)
- Modify: `src/masova_agent/main.py` (`list_action_proposals` route)
- Test: `tests/test_proposals.py` (existing file — append)

**Interfaces:**
- Consumes: nothing new.
- Produces: `list_proposals(..., type: Optional[str] = None)` — extends the
  existing signature; callers passing no `type` get identical behavior to
  today (backward compatible).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_proposals.py`, inside `TestProposalStore` (or the
class covering `list_proposals` — match the existing test class structure
in that file):

```python
    def test_list_proposals_filters_by_type(self):
        from masova_agent.runtime.models import ActionProposal
        from masova_agent.runtime import proposal_store

        p1 = ActionProposal(type="DRAFT_PURCHASE_ORDER", store_id="DOM014", summary="s1", rationale="r1", agent="inventory_reorder")
        p2 = ActionProposal(type="DRAFT_CHURN_CAMPAIGN", store_id="DOM014", summary="s2", rationale="r2", agent="churn_prevention")
        proposal_store.save_proposal(p1)
        proposal_store.save_proposal(p2)

        results = proposal_store.list_proposals(type="DRAFT_PURCHASE_ORDER")
        assert len(results) == 1
        assert results[0]["type"] == "DRAFT_PURCHASE_ORDER"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_proposals.py -v -k filters_by_type`
Expected: FAIL with `TypeError: list_proposals() got an unexpected keyword argument 'type'`

- [ ] **Step 3: Add the filter**

In `src/masova_agent/runtime/proposal_store.py`, modify `list_proposals`:

```python
def list_proposals(
    *,
    store_id: Optional[str] = None,
    status: Optional[str] = None,
    agent: Optional[str] = None,
    type: Optional[str] = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    _load_file_once()
    with _lock:
        rows = list(_by_id.values())
    if store_id:
        rows = [r for r in rows if r.get("store_id") == store_id]
    if status:
        rows = [r for r in rows if str(r.get("status")) == status]
    if agent:
        rows = [r for r in rows if r.get("agent") == agent]
    if type:
        rows = [r for r in rows if r.get("type") == type]
    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return rows[: max(1, min(limit, 500))]
```

- [ ] **Step 4: Thread the query param through the route**

In `src/masova_agent/main.py`, modify `list_action_proposals`:

```python
@app.get("/agent/proposals", dependencies=[Depends(require_scope("read:proposals"))])
async def list_action_proposals(
    storeId: Optional[str] = None,
    status: Optional[str] = None,
    agent: Optional[str] = None,
    type: Optional[str] = None,
    limit: int = 100,
):
    from .runtime import proposal_store

    return {
        "proposals": proposal_store.list_proposals(
            store_id=storeId, status=status, agent=agent, type=type, limit=limit
        )
    }
```

(This route already reads `require_scope("read:proposals")` if Phase 2 has
landed — if this plan is executed before Phase 2, keep the existing
`Depends(verify_trigger_api_key)` and let Phase 2's plan handle the
substitution when it runs; don't duplicate that change here.)

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_proposals.py -v`
Expected: PASS, including the new test, no regressions in the existing
`list_proposals`/`GET /agent/proposals` tests

- [ ] **Step 6: Commit**

```bash
git add src/masova_agent/runtime/proposal_store.py src/masova_agent/main.py tests/test_proposals.py
git commit -m "feat: add type filter to GET /agent/proposals"
```

---

### Task 2: Auto-expire stale pending proposals

**Files:**
- Create: `src/masova_agent/runtime/proposal_expiry.py`
- Modify: `src/masova_agent/scheduler/scheduler.py` (`register_jobs`)
- Test: `tests/test_proposals.py` (append)

**Interfaces:**
- Consumes: `proposal_store.list_proposals(status="PENDING")`,
  `proposal_store.resolve_proposal(id, "EXPIRED", note=...)` (both exist
  already).
- Produces: `sweep_expired(max_age_hours: int = 72) -> int` (returns count
  swept) — registered as a scheduler job, no other module depends on it.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_proposals.py`:

```python
    def test_sweep_expired_resolves_stale_pending_proposals(self):
        from datetime import datetime, timedelta, timezone
        from masova_agent.runtime.models import ActionProposal
        from masova_agent.runtime import proposal_store, proposal_expiry

        stale = ActionProposal(type="DRAFT_PURCHASE_ORDER", store_id="DOM014", summary="old", rationale="r", agent="inventory_reorder")
        stale.created_at = (datetime.now(timezone.utc) - timedelta(hours=100)).isoformat()
        proposal_store.save_proposal(stale)

        fresh = ActionProposal(type="DRAFT_PURCHASE_ORDER", store_id="DOM014", summary="new", rationale="r", agent="inventory_reorder")
        proposal_store.save_proposal(fresh)

        count = proposal_expiry.sweep_expired(max_age_hours=72)
        assert count == 1

        stale_after = proposal_store.get_proposal(stale.proposal_id)
        fresh_after = proposal_store.get_proposal(fresh.proposal_id)
        assert stale_after["status"] == "EXPIRED"
        assert fresh_after["status"] == "PENDING"

    def test_resolve_rejects_expired_as_client_submitted_status(self):
        from masova_agent.runtime.models import ActionProposal
        from masova_agent.runtime import proposal_store

        p = ActionProposal(type="X", store_id="DOM014", summary="s", rationale="r", agent="a")
        proposal_store.save_proposal(p)

        with pytest.raises(ValueError):
            proposal_store.resolve_proposal(p.proposal_id, "EXPIRED", note="client tried to set this")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_proposals.py -v -k "sweep_expired or rejects_expired"`
Expected: FAIL — `test_sweep_expired_resolves_stale_pending_proposals` fails
with `ModuleNotFoundError: No module named 'masova_agent.runtime.proposal_expiry'`;
`test_resolve_rejects_expired_as_client_submitted_status` should already
PASS today (this confirms `resolve_proposal`'s existing validation
already rejects `EXPIRED`, per `proposal_store.py:97` — a check, not a
new behavior)

- [ ] **Step 3: Write `proposal_expiry.py`**

```python
# src/masova_agent/runtime/proposal_expiry.py
"""
Sweeps stale PENDING proposals to EXPIRED. EXPIRED is a system-only
outcome — resolve_proposal (proposal_store.py) already rejects it as a
client-submitted status; this module is the only code path that reaches
it, run on a schedule rather than left as a dead enum value.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from . import proposal_store

logger = logging.getLogger(__name__)

DEFAULT_MAX_AGE_HOURS = 72


def sweep_expired(max_age_hours: int = DEFAULT_MAX_AGE_HOURS) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    pending = proposal_store.list_proposals(status="PENDING", limit=500)
    swept = 0
    for row in pending:
        created_at = row.get("created_at") or ""
        try:
            created = datetime.fromisoformat(created_at)
        except ValueError:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if created < cutoff:
            try:
                proposal_store.resolve_proposal(
                    row["proposal_id"], "EXPIRED", note=f"auto-expired after {max_age_hours}h"
                )
                swept += 1
            except Exception as e:
                logger.warning("failed to auto-expire proposal %s: %s", row.get("proposal_id"), e)
    return swept
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_proposals.py -v -k "sweep_expired or rejects_expired"`
Expected: PASS (2 tests)

- [ ] **Step 5: Register the daily sweep job**

In `src/masova_agent/scheduler/scheduler.py`, inside `register_jobs()`:

```python
    from ..runtime.proposal_expiry import sweep_expired

    # Auto-expire stale pending proposals — daily at 3am IST
    scheduler.add_job(
        sweep_expired,
        trigger="cron",
        hour=3,
        minute=0,
        id="proposal_expiry_sweep",
        name="Proposal Expiry Sweep",
        replace_existing=True,
    )
```

Add this alongside the other `scheduler.add_job(...)` calls, before the
final `logger.info("Registered %d scheduled agent jobs", ...)` line.

- [ ] **Step 6: Update the registered-jobs count assumption in Phase 1's registry tests, if that plan has landed**

If `tests/test_registry.py` (Phase 1) asserts an exact job count anywhere,
this adds one more scheduler job (`proposal_expiry_sweep`) that isn't one
of the 8 agents — check that Phase 1's `build_registry()` only iterates
`AGENT_ALLOWLISTS` (8 entries), not `get_scheduler().get_jobs()` directly,
so this new job doesn't spuriously appear as a 9th "agent." Confirm by
re-running: `pytest tests/test_registry.py -v` (only relevant if Phase 1 is
already implemented when this task runs).

- [ ] **Step 7: Run the full test suite to check for regressions**

Run: `pytest tests/ -v --ignore=tests/test_scenarios.py`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/masova_agent/runtime/proposal_expiry.py src/masova_agent/scheduler/scheduler.py tests/test_proposals.py
git commit -m "feat: auto-expire stale pending proposals via a daily sweep job"
```

---

### Task 3: Document the finalized API contract

**Files:**
- Modify: `docs/AGENT_PLATFORM.md` ("ActionProposal closed loop" section)

**Interfaces:** none (documentation only)

- [ ] **Step 1: Update the docs**

In `docs/AGENT_PLATFORM.md`'s "ActionProposal closed loop" section, update
the `List` row and add an `Expire` row:

```markdown
| List | `GET /agent/proposals?storeId=&status=&agent=&type=` (read:proposals scope) |
| Expire | Daily sweep (`runtime/proposal_expiry.py::sweep_expired`, 72h threshold) resolves stale `PENDING` proposals to `EXPIRED` — the only path that ever sets this status; `resolve` rejects it as a client-submitted value |
```

- [ ] **Step 2: Commit**

```bash
git add docs/AGENT_PLATFORM.md
git commit -m "docs: document the finalized proposal review API contract"
```

---

## Self-Review Notes

- **Spec coverage:** Gap 1 (CORS — spec confirmed no code change needed,
  correctly has no task here), Gap 2 (EXPIRED sweep — Task 2), Gap 3 (type
  filter — Task 1), documented contract (Task 3). The spec's "already
  built" assessment for `GET`/`resolve` themselves is why this plan has no
  task rebuilding them.
- **Placeholder scan:** none found.
- **Type consistency:** `list_proposals(..., type: Optional[str] = None)`
  (Task 1) matches the route's new `type: Optional[str] = None` query param
  and `sweep_expired(max_age_hours: int = 72) -> int` (Task 2) matches its
  scheduler registration (no args passed, uses the default).
