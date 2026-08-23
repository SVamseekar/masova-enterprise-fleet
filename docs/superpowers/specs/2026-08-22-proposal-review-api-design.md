# Proposal Review + In-Repo Console — Design Spec

Status: **revised 2026-08-22** (review pass). Phase 6 of 7.
Track: All Things Agentic Hackathon — The Fortified Enterprise Fleet
Pillar: 2 — "What is it allowed to do?"
Inherits: [hackathon-constraints.md](./2026-08-22-hackathon-constraints.md)

## Problem, reassessed

`GET /agent/proposals` and `POST /agent/proposals/{id}/resolve` already
exist. The original readiness plan treated this phase as "wire the MaSoVa
manager frontend." That frontend is **another repo** and is **not** what
judges clone.

The product for this submission is this service plus
`docs/hackathon/fleet-console-mockup.html` served by FastAPI and talking
to the live APIs. Without that, the demo has no manager-facing Approve,
and the "database updates or UI changes" bar is a curl session.

## What this phase covers

1. Close two real API gaps (type filter, EXPIRED sweep).
2. DEMO_MODE apply-on-approve (contract defined in Phase 5; wired here if
   not already called from resolve).
3. Serve and wire the in-repo console to live endpoints.

## Gap 1 — CORS

Keep `CORS_ORIGINS`. Serving the console from this same origin makes CORS
irrelevant for the demo. If the file is opened as `file://`, fetch will
fail — so it must be served (`GET /console`).

## Gap 2 — `EXPIRED` producer

`ProposalStatus` includes `EXPIRED` but nothing sets it. Add
`runtime/proposal_expiry.py`: `sweep_expired(max_age_hours: int = 72) -> int`,
daily APScheduler job, resolves stale PENDING to EXPIRED. Client
`resolve` still rejects `EXPIRED` as a submitted status.

## Gap 3 — `type` filter

`GET /agent/proposals` gains `type=` threaded into `list_proposals`.

## Gap 4 — apply on approve (DEMO_MODE)

`POST /agent/proposals/{id}/resolve` with `APPROVED`, when `DEMO_MODE=true`,
calls `proposal_apply.apply(proposal)` (Phase 5) **after** the JSONL
status update. Failure to apply does not roll back the audit resolve; it
logs and returns `applied: false` on the response so the console can show
it. `DEMO_MODE=false`: `applied` omitted / false, no SQL.

## Gap 5 — in-repo console (the demo UI)

`GET /console` serves `docs/hackathon/fleet-console-mockup.html` (or a
copy under `src/masova_agent/static/console.html` if that is easier for
the Docker COPY). Vanilla JS already in that file is replaced/extended to:

- `GET /agents` → left rail (name, category, last_run, status chip)
- `GET /agent/proposals?status=PENDING` → decision cards
- `GET /agent/runs?limit=` → activity / "running now" from last traces
- Approve / Decline → `POST /agent/proposals/{id}/resolve`
- "Why this decision" opens `GET /agent/runs/{run_id}` and renders
  `reasoning_trace[].result_summary` as "what the agent saw"
- Auth: a demo manager key from `AGENT_API_KEYS` (or the legacy master
  key) stored in a local input or a `data-demo-key` that is **only**
  present when `DEMO_MODE=true`. Never hardcode a production secret.

The page stays self-contained (inline CSS, no CDN) per DESIGN_NOTES.

Three manager views, all in this file:

- **Needs your OK** — proposal queue, Approve/Decline.
- **Live run** — kitchen-pass canvas. Stations = scheduler, agent identity, each tool (`list_low_stock`, Open-Meteo, draft PO), HITL, manager. Replay lights them in call order. This is the n8n-style "see the graph" without copying n8n's UI.
- **Store proof** — before/after ledger for mozzarella, tomato, PO, menu price, consent split. Approve on the inventory card mutates the PO column. Menu price must stay still.

Phase 6 wiring: canvas reads `GET /agent/runs/{id}.reasoning_trace`; ledger reads `GET /agent/demo/tables/inventory` and `purchase_orders`. Until those APIs exist, the mockup plays the same closed loop from the seeded scenario so the video storyboard is already true to the data.

## API contract

```
GET /agent/proposals?storeId=&status=&agent=&type=&limit=
  require_scope("read:proposals")
  → {"proposals": [ActionProposal.to_dict(), ...]}

POST /agent/proposals/{id}/resolve
  require_scope("resolve:proposals")
  body: {"status": "APPROVED" | "REJECTED", "note": str | null}
  → ActionProposal.to_dict() plus optional "applied": bool
  → 404 unknown id; 400 invalid status (EXPIRED is system-only)

GET /console
  unauthenticated GET of the HTML (static). API calls from the page
  still send X-Agent-Api-Key.
```

## Testing

- Existing `tests/test_proposals.py`: type filter; sweep expires old,
  leaves fresh; client cannot POST EXPIRED.
- DEMO_MODE: approve applies SQLite (reuse Phase 5 golden path).
- `GET /console` returns 200 and HTML containing `Masova Agent Fleet`.
- Optional: TestClient approve from a seeded pending proposal updates
  list length.

## Out of scope

- MaSoVa manager frontend (`AIAgentsSection.tsx`, `agentApi.ts`)
- Redesigning the mockup's visual language (already revised; wire it)
