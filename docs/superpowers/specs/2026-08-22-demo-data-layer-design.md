# Demo Data Layer — Design Spec

Status: draft (auto-authored per user instruction to proceed through all 7 phases without per-decision confirmation)
Track: All Things Agentic Hackathon — The Fortified Enterprise Fleet
Pillar: 2 — "What is it allowed to do?" (proof-of-execution substrate)

## Problem

Every tool that reads/writes platform state goes over HTTP to
`BACKEND_URL` (`tools/ops_tools.py::_get/_post`, `tools/backend_tools.py`,
`tools/ops_http.py`) — a live MaSoVa platform backend at
`192.168.50.88:8080` that (a) won't be reachable from wherever the demo is
recorded/hosted, and (b) per `CLAUDE.md`'s own known-issue note, has
confirmed field-shape drift against this service's assumptions in at least
`backend_tools.py`. The judging bar explicitly wants "proof of live
execution — database updates or UI changes," which needs a real database
the demo can show rows changing in, not a live call to an unreachable host.

## Constraint carried forward

The demo backend must be a real, queryable data store that tools actually
read from and write to at request time — not inline dicts returned by a
function pretending to be a database call. Seed data must be planted once,
then mutated by genuine tool execution during the demo, not regenerated
per call.

## Design

### Contract source of truth

`tests/fixtures/backend_contracts.py` already documents the real canonical
field shapes (from `shared-models`) versus legacy/dual-tolerant ones this
service accepts — order status enum, `operatingConfig` vs flat store-hours
fields, Spring `{content: [...]}` paging, minor-unit prices. This spec
reuses that file as the schema authority for seeding and for auditing
`backend_tools.py`/`ops_tools.py` against it, rather than inventing a new
contract by hand.

### SQLite store

`data/demo/masova_demo.sqlite` (gitignored, like `data/proposals/`),
built by `scripts/seed_demo_data.py`. Tables mirror the shapes in
`backend_contracts.py`: `stores`, `menu_items`, `orders`, `customers`,
`inventory`, `staff_shifts`, `purchase_orders`, `reviews`. One seeded
store: `DOM014`, Lisbon, EUR minor units (cents), matching the plan's
EU/Lisbon framing. 18 scenarios spread across the 8 agents (low stock
triggering a reorder proposal, a churn-risk customer segment, a 1★ review,
a kitchen-overload window, etc.) — enumerated as seed rows, not as
special-cased mock responses.

### Adapter, not a parallel code path

New `services/demo_backend.py` implements the same call shape as
`tools/ops_http.py`'s outbound helpers (`_get(path, params)`, `_post(path,
body)`) but executes real SQL against the SQLite file instead of an HTTP
request. Selection happens once, at the same call sites that currently
build a `BACKEND_URL` request:

```python
def _get(path: str, params: dict | None = None) -> dict:
    if demo_mode():
        return demo_backend.get(path, params)
    ... existing httpx call ...
```

`demo_mode()` reads `DEMO_MODE` (env, live-checked per call — not cached at
import time, so toggling it doesn't need a restart mid-development). Tools
themselves (`ops_tools.py`, `backend_tools.py`) are unchanged — they only
ever call `_get`/`_post`; the swap is invisible above that layer, which is
exactly why `AgentRuntime`/`ops_llm.py`'s tool loop needs no changes to run
against demo data.

### Fixing the confirmed drift

While building `demo_backend.py` against `backend_contracts.py`'s
canonical shapes, audit `backend_tools.py` (customer chat tools) and
`ops_tools.py` (ops tools) field-by-field against that same file and
correct any place a tool reads a field name the canonical shape doesn't
actually use. (A partial pass already exists — `ops_tools.py` already
reads `minimumStock`/`price` correctly per the current source; the
remaining audit surface is narrower than the original plan assumed and
gets confirmed, not assumed, during implementation.)

## Error handling

- Demo backend query failure (bad seed data, missing table) → same
  `_map_http_error`-style translation tools already use for HTTP failures,
  so callers don't need to know which backend answered
- `DEMO_MODE=true` with no seeded SQLite file present → fail loudly at
  first call with a clear "run scripts/seed_demo_data.py first" error,
  never silently fall through to live `BACKEND_URL` (that would silently
  point the demo at an unreachable/wrong host)

## Testing

- `tests/test_demo_backend.py`: seeded rows round-trip through
  `demo_backend.get/post` matching the shapes `backend_contracts.py`
  declares canonical
- Existing `tests/test_backend_contracts.py` / `tests/test_backend_tools.py`
  gain a `DEMO_MODE=true` parametrization so the same golden-path
  assertions run against real seeded SQLite, not just mocks
- One test drives a full agent run (e.g. inventory reorder) against
  `DEMO_MODE=true` and asserts a row in `purchase_orders` actually changed
  — the literal "proof of live execution" the judging bar asks for

## Out of scope

- Any change to the real MaSoVa platform backend — this is a local stand-in
  used only when `DEMO_MODE=true`; production/live-backend behavior is
  untouched
- Seeding non-Lisbon markets — one market is enough for the demo script
