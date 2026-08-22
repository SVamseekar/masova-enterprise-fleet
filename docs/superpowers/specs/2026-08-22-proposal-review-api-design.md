# Proposal Review API — Design Spec

Status: draft (auto-authored per user instruction to proceed through all 7 phases without per-decision confirmation)
Track: All Things Agentic Hackathon — The Fortified Enterprise Fleet
Pillar: 2 — "What is it allowed to do?"

## Problem, reassessed against actual code

The readiness plan describes this phase as "80% built → wire the rest,"
assuming the approve/reject panel is the only missing piece. Checking
`main.py` directly: `GET /agent/proposals` and `POST
/agent/proposals/{id}/resolve` are already implemented, already documented
in `AGENT_PLATFORM.md`, and already back the `ActionProposal` closed loop
(`proposal_store.py`). **This repo's backend surface for Phase 6 is
already done.** The actual gap — the approve/reject panel UI itself,
`AIAgentsSection.tsx`, the frontend's `agentApi.ts` mutations — lives in
the separate manager frontend repo, which is not part of
`masova-enterprise-fleet` (confirmed: no `.tsx`/frontend code exists in
this repo).

## What this spec actually covers

Since the UI work is out of this repo, this phase becomes: (1) confirm the
existing API is genuinely sufficient for a review panel to be built against
it, (2) close the small real gaps found while checking, (3) document the
contract clearly enough that the frontend repo's work isn't blocked on
asking questions back into this one.

### Gap 1 — CORS

`CORS_ORIGINS` (`config/env.example`) already includes
`http://localhost:5173,http://localhost:3000,http://localhost:8080` —
covers Vite and CRA dev servers already. No change needed unless the
manager frontend's actual deployed origin differs; that's a per-environment
config value, not a code gap.

### Gap 2 — `EXPIRED` status has no producer

`ProposalStatus` (`runtime/models.py`) defines `PENDING | APPROVED |
REJECTED | EXPIRED`, and `resolve_action_proposal` accepts `EXPIRED` as a
valid resolution, but nothing ever sets a proposal to `EXPIRED`
automatically — a stale pending proposal sits `PENDING` forever unless a
manager manually resolves it. Add a small `runtime/proposal_expiry.py`:
`sweep_expired(max_age_hours: int = 72) -> int`, called once at scheduler
startup registration (`scheduler.py::register_jobs`) as a daily job,
walking `proposal_store.list_proposals(status="PENDING")` and calling
`proposal_store.resolve_proposal(id, "EXPIRED", note="auto-expired after
72h")` for anything older than the threshold. This is a real gap (a defined
enum value with no code path ever reaching it), not a nice-to-have
invention.

### Gap 3 — no risk/type filter on list

`GET /agent/proposals` already filters by `storeId`, `status`, `agent`. A
review panel will likely also want to filter by proposal `type` (e.g. show
only `DRAFT_PURCHASE_ORDER`) — add `type: Optional[str] = None` as a fourth
query param, passed through to `proposal_store.list_proposals`, which
already accepts arbitrary field filtering internally and just needs the one
new parameter threaded from the route.

## API contract (for the frontend repo to build against)

```
GET /agent/proposals?storeId=&status=&agent=&type=&limit=
  require_scope("read:proposals")     # Phase 2
  → {"proposals": [ActionProposal.to_dict(), ...]}

POST /agent/proposals/{id}/resolve
  require_scope("resolve:proposals")  # Phase 2
  body: {"status": "APPROVED" | "REJECTED", "note": str | null}
  → ActionProposal.to_dict() with status/resolution_note/resolved_at set
  → 404 if proposal_id unknown
  → 400 if status is not APPROVED/REJECTED (EXPIRED is system-only, via the sweep job)
```

## Error handling

Unchanged from existing behavior — `resolve_action_proposal` already 400s
on an invalid status string and 404s on an unknown id; the sweep job logs
and continues past ay proposal it fails to resolve on a given run rather
than raising, run being a daily cron job by APScheduler rather than a
user-facing call.

## Testing

- Existing `tests/test_proposals.py` gains: `type` filter returns only
  matching proposals; a proposal older than the sweep threshold gets
  `EXPIRED` after `sweep_expired()` runs; a proposal younger than the
  threshold is untouched; `resolve` still rejects `EXPIRED` as a
  client-submitted status (system-only)

## Out of scope (explicitly, lives in the other repo)

- The actual approve/reject panel component, `AIAgentsSection.tsx` wiring,
  `agentApi.ts` mutations — manager frontend repo, not tracked here
- Any visual/design work — this repo produces API contract only
