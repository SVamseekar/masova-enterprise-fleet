# Agent Registry — Design Spec

Status: **revised 2026-08-22** (review pass). Phase 1 of 7.
Track: All Things Agentic Hackathon — The Fortified Enterprise Fleet
Pillar: 1 — "Who is behind this agent?"
Inherits: [hackathon-constraints.md](./2026-08-22-hackathon-constraints.md)

## Problem

There is no discoverable catalog of the 8 agents. There is no `GET /agents`.
The manager frontend in another repo hardcodes a static list; that frontend
is **not** the hackathon product. This endpoint is what the in-repo console
and the demo's "discover the fleet" beat call.

## Constraint

No hardcoding of operational data. Every catalog field is derived from
running code, scheduler state, or the run store. Allowed authored data:
display `name` only. `category` is derived (scheduler job → `scheduled`;
`support_chat` → `chat`; `review_response` → `event`).

## Design

### Data flow

```
GET /agents  (Phase 1: verify_trigger_api_key; Phase 2: require_scope("read:registry"))
    → runtime/registry.py: build_registry()
        → AGENT_ALLOWLISTS (wrap.py)              agent id + tool names
        → DEFAULT_TOOL_REGISTRY (policy.py)       RiskTier per tool
        → scheduler.get_scheduler().get_jobs()    trigger + schedule
        → FastAPI app.routes                      endpoint path
        → run_store.get_last_run(agent_id)        last-run summary
    → {"agents": [ ... ]}
```

Envelope is `{"agents": [...]}` to match `{"proposals": [...]}`.

### Run store (slice of Phase 3, required for honest `last_run`)

`AuditLogger.log_run()` today is in-process + logger only.

New `runtime/run_store.py`, same pattern as `proposal_store.py`:

- Append the **redacted audit record** (what `log_run` already builds), not
  `AgentRunResult.to_dict()`. Full `output` / proposal payloads never hit disk.
- Add `at: _utc_now_iso()` on that record. `AgentRunResult` has no timestamp
  today; `at` is created at log time. Do not invent it at read time.
- In-memory `dict[agent_name, record]`, later JSONL lines win, threading lock,
  lazy load-once, `RUN_DATA_DIR` override, gitignored under `data/runs/`.
- `record_run(record) -> dict`
- `get_last_run(agent_name) -> dict | None` returns only
  `{status, used_fallback, at, trigger_type}` (project; do not leak
  proposal summaries to the catalog).
- `clear_for_tests()`

**Write path (one, not two):** `AuditLogger.log_run` always calls
`run_store.record_run` after redaction. Tests go through `log_run` or
`record_run` for store unit tests; registry tests that need a last-run
must either `log_run` a real `AgentRunResult` or `record_run` a summary.
Do not persist via a backdoor that production never calls.

Cloud Run disk is ephemeral — `last_run` is honest for the life of the
instance (`--max-instances=1` in Phase 7). Out of scope to put this on
Firestore for the hackathon.

### API contract

```
GET /agents
200 OK
{
  "agents": [
    {
      "id": "inventory_reorder",
      "name": "Inventory Reorder",
      "category": "scheduled" | "chat" | "event",
      "trigger_type": "cron" | "interval" | "chat" | "rabbitmq+manual",
      "schedule": "every 6h" | "<cron fields from APScheduler>" | null,
      "tool_allowlist": [{"name": "list_low_stock", "tier": "READ"}, ...],
      "last_run": {
        "status": "ok",
        "used_fallback": false,
        "at": "2026-08-22T09:03:11+00:00",
        "trigger_type": "scheduled"
      } | null,
      "endpoint": "/agents/inventory-reorder/trigger"
    }
  ]
}
```

Two different `trigger_type` vocabularies — keep both, do not collapse:

| Where | Values | Source |
|---|---|---|
| Catalog `trigger_type` | `cron` / `interval` / `chat` / `rabbitmq+manual` | APScheduler trigger class, or structural absence of a job |
| `last_run.trigger_type` | `scheduled` / `manual` / `chat` / `event` | `AgentRunRequest.trigger_type` as the run actually used |

### Field sources

| Field | Source |
|---|---|
| `id` | `AGENT_ALLOWLISTS` keys |
| `name` | authored label map in `registry.py` |
| `category` | derived: job present → `scheduled`; `support_chat` → `chat`; `review_response` → `event` |
| catalog `trigger_type`, `schedule` | live job via `_describe_trigger`; if job missing and agent is scheduled-type → `null` (never 500) |
| `tool_allowlist` | allowlist ∩ `DEFAULT_TOOL_REGISTRY`; **no EXECUTE** |
| `last_run` | `run_store.get_last_run` projection |
| `endpoint` | declared `ENDPOINT_MAP` **plus** a test that every value exists on `app.routes`. `support_chat` → `POST /agent/chat`. Hyphenation of ids is not a derivation function (chat would be wrong). |

### Error handling

- Missing/wrong `X-Agent-Api-Key` → 401 (`verify_trigger_api_key`).
- Scheduler not started → `schedule`/`trigger_type` null for scheduled agents, never 500.
- Missing run file → `last_run: null`, warning log.

### Testing (`tests/test_registry.py` + `tests/test_run_store.py`)

1. Exactly the 8 `AGENT_ALLOWLISTS` ids.
2. After `register_jobs()`, inventory `trigger_type == "interval"` and schedule contains `6h`; demand is `cron` with a non-empty schedule — inspect `scheduler.get_jobs()`, do not parse source.
3. `support_chat` category `chat`, schedule null, endpoint `/agent/chat`.
4. `review_response` category `event`, trigger `rabbitmq+manual`.
5. `last_run` is null with no records.
6. After `AuditLogger.log_run(AgentRunResult(...))`, `last_run` has status, used_fallback, **at** (iso timestamp), trigger_type.
7. HTTP: no key / wrong key → 401; good key → 200 and `agents` length 8.
8. No allowlisted tool is EXECUTE.
9. Every `endpoint` is registered on `app.routes` (method-aware: chat is POST, catalog is GET).

## Out of scope

- Per-agent keys → Phase 2
- Full reasoning trace on the catalog payload → Phase 3 (`GET /agent/runs`)
- Console consumption → Phase 6 (this repo's mockup, not the other frontend)
