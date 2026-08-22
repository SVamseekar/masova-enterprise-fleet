# Agent Registry — Design Spec

Status: approved · Phase 1 of 7, [Fleet Readiness Plan](../../hackathon/fleet-readiness-plan.html)
Track: All Things Agentic Hackathon — The Fortified Enterprise Fleet
Pillar: 1 — "Who is behind this agent?"

## Problem

There is no discoverable catalog of the 8 agents in this fleet. The manager
frontend (separate repo) hardcodes its own static agent list. There is no
`GET /agents` endpoint. This is the clearest gap in the "Know-Your-Agent"
identity pillar and the plan's own recommended starting point: no
dependencies on the other 6 phases, backend-only, fully testable locally.

## Constraint carried into every phase

No hardcoding, anywhere. Every value the registry reports must be derived
from something live — running code, a real data store, or a real API call —
never a static stand-in for what should be computed or fetched. The only
exception is human-authored *display* metadata (agent display name,
category label) that has no live source to derive from and isn't itself
operational data.

## Design

### Data flow

```
GET /agents  (verify_trigger_api_key)
    → runtime/registry.py: build_registry()
        → AGENT_ALLOWLISTS (wrap.py)         — agent id + tool allowlist
        → POLICY / RiskTier (policy.py)      — tier per tool
        → scheduler.get_scheduler().get_jobs() — trigger type + schedule, live
        → run_store.get_last_run(agent_id)   — most recent run status
    → JSON array response
```

### Persisting run records (pulled forward from Phase 3)

`AuditLogger.log_run()` (`runtime/audit.py`) currently only appends to an
in-process list and the Python logger — lost on restart, and with no way for
the registry to read "last run" honestly.

Extend it, mirroring `runtime/proposal_store.py`'s exact pattern:

- Append each `AgentRunResult.to_dict()` to `data/runs/runs.jsonl`
  (append-only, gitignored, same convention as `data/proposals/`)
- In-memory `dict[str, dict]` keyed by `agent_name` → most recent record,
  for fast lookup without re-reading the file per request
- Lazy load-once from the JSONL file on cold start (mirrors
  `proposal_store._load_file_once`)
- Thread lock around read/write (mirrors `proposal_store._lock`)
- New function: `get_last_run(agent_name: str) -> dict | None`

This is a genuine slice of Phase 3 (reasoning-chain observability) landing
early, because Phase 1's `status` field has nowhere honest to read from
otherwise. Phase 3 builds the structured per-tool-call trace on top of this
same persisted-run foundation; it does not redo the persistence itself.

### API contract

```
GET /agents
Header: X-Agent-Api-Key: <AGENT_TRIGGER_API_KEY>   (same dependency as
                                                     existing /agents/{name}/trigger routes)

200 OK
[
  {
    "id": "inventory_reorder",
    "name": "Inventory Reorder",
    "category": "scheduled" | "chat" | "event",
    "trigger_type": "cron" | "interval" | "chat" | "rabbitmq+manual",
    "schedule": "every 6h" | "cron 0 2 * * *" | null,
    "tool_allowlist": [
      {"name": "list_low_stock", "tier": "READ"},
      {"name": "create_draft_po", "tier": "PROPOSE"},
      ...
    ],
    "last_run": {
      "status": "ok",
      "used_fallback": false,
      "at": "2026-08-22T09:03:11+00:00",
      "trigger_type": "scheduled"
    } | null,
    "endpoint": "/agents/inventory-reorder/trigger"
  },
  ...
]
```

Fields and their source, explicitly:

| Field | Source | Live? |
|---|---|---|
| `id` | `AGENT_ALLOWLISTS` keys | derived |
| `name`, `category` | small hand-authored label map in `registry.py` | static display metadata (not operational) |
| `trigger_type`, `schedule` | `scheduler.get_scheduler().get_jobs()`; `support_chat`/`review_response` special-cased since they have no scheduler job | derived |
| `tool_allowlist` | `AGENT_ALLOWLISTS` + `RiskTier` per tool from `policy.py` | derived |
| `last_run` | `run_store.get_last_run(id)` | derived, persisted |
| `endpoint` | matches the actual route registered in `main.py` | derived (kept in sync by a test asserting route existence) |

No `version` field — there is no real versioning system behind one yet;
inventing a static `"v1"` would itself be the hardcoding this project rules
out. Add it later only when it means something (e.g. a real deploy/build id).

### Error handling

- Missing/wrong `X-Agent-Api-Key` → 401, same as existing trigger routes
  (`verify_trigger_api_key` dependency, reused as-is)
- Scheduler not yet started (edge case: called before `lifespan` startup
  registers jobs) → `trigger_type`/`schedule` fall back to `null` for
  scheduled agents rather than raising; the endpoint never 500s because a
  job isn't registered yet
- `run_store` file missing or unreadable → treated as "no runs yet" (`None`
  per agent), logged as a warning, never raised to the caller — same
  resilience posture as `proposal_store._load_file_once`

### Testing

New `tests/test_registry.py`:

1. Registry returns exactly the 8 agent ids in `AGENT_ALLOWLISTS`, no more,
   no fewer
2. Each scheduled agent's `schedule`/`trigger_type` matches what
   `scheduler.py` actually registers (cross-checked against the literal
   `add_job(...)` calls, not duplicated by hand)
3. `support_chat` and `review_response` report `category: "chat"` /
   `"event"` with `schedule: null`
4. `last_run` is `null` for an agent with no persisted run record
5. After calling `run_store.record_run(...)` (or `AuditLogger.log_run`) for
   an agent, `last_run` reflects it — status, `used_fallback`, timestamp
6. `GET /agents` without `X-Agent-Api-Key` → 401; with the wrong key → 401;
   with the correct key → 200
7. `tool_allowlist` tiers match `policy.py`'s registered `RiskTier` for each
   tool name — no `EXECUTE`-tier tool ever appears (regression guard shared
   with the existing policy tests)

## Out of scope (deferred to later phases)

- Per-agent scoped credentials replacing the shared trigger key → Phase 2
- Structured per-tool-call reasoning trace beyond outcome + last-run → Phase 3
- Any UI consuming this endpoint → Phase 6 (proposal review UI), and the
  separate manager frontend repo, not this repo
