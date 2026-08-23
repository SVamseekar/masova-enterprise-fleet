# Agent Identity — Design Spec

Status: **revised 2026-08-22** (review pass). Phase 2 of 7.
Track: All Things Agentic Hackathon — The Fortified Enterprise Fleet
Pillar: 1 — "Who is behind this agent?"
Depends on: Phase 1 (Agent Registry) — re-gates its route surface
Inherits: [hackathon-constraints.md](./2026-08-22-hackathon-constraints.md)

## Problem

Every internal route — the 7 `/agents/{name}/trigger` endpoints, `GET /agents`
(Phase 1), `GET /agent/proposals`, `POST /agent/proposals/{id}/resolve` — is
gated by one dependency, `verify_trigger_api_key` (`auth.py`), checking a
single static `AGENT_TRIGGER_API_KEY` env value. A key leaked or misused for
one agent can trigger all seven. There is no way to answer "which caller
triggered this run" beyond "someone with the shared key" — the literal gap
the "who is behind this agent" pillar calls out.

## Constraint carried forward

No hardcoding: credential-to-scope mapping must be loaded live from
configuration at request time (so it can be rotated/extended without code
changes), never a static per-key dict baked into source.

## Design

### Scope model

Four scope kinds, each a plain string:

- `trigger:<agent_id>` — call `/agents/<agent-id>/trigger` for that one agent
- `read:registry` — call `GET /agents`
- `read:runs` — call `GET /agent/runs` and `GET /agent/runs/{run_id}` (Phase 3)
- `read:proposals` — call `GET /agent/proposals`
- `resolve:proposals` — call `POST /agent/proposals/{id}/resolve`

The in-repo console (Phase 6) uses a manager credential with
`read:registry`, `read:runs`, `read:proposals`, `resolve:proposals`, and
the trigger scopes it needs for the demo. The scheduler process keeps `*`.

A credential is `{key: str, scopes: list[str]}`. A credential holding `"*"`
in its scope list is a master credential (all scopes) — the scheduler and
manager backend get one for now; this keeps the migration incremental
without inventing a policy engine phase 2 doesn't need.

### Loading credentials — live, not hardcoded

New env var `AGENT_API_KEYS`, a JSON array, parsed at process start and on
`reload_config()` (mirrors how `utils/config.py` already reloads on env
change):

```json
[
  {"key": "sched-...", "scopes": ["*"]},
  {"key": "inv-...", "scopes": ["trigger:inventory_reorder", "read:registry"]}
]
```

`AGENT_TRIGGER_API_KEY` (the current single key) becomes the seed value for
one master credential when `AGENT_API_KEYS` is unset, so existing deploys
and the scheduler's in-process calls keep working without a breaking change
on day one — this is a migration path, not a permanent duplicate mechanism;
`AGENT_TRIGGER_API_KEY` should be considered deprecated once real per-agent
keys are issued.

Module: `src/masova_agent/runtime/identity.py`

```python
@dataclass(frozen=True)
class AgentCredential:
    key: str
    scopes: frozenset[str]

def load_credentials() -> dict[str, AgentCredential]: ...  # key -> credential, live from env
def require_scope(scope: str) -> Callable[..., Awaitable[None]]:
    """FastAPI dependency factory — returns a dependency checking X-Agent-Api-Key
    grants `scope` (directly or via '*')."""
```

### Route wiring (`main.py`)

Each `/agents/{name}/trigger` route's `dependencies=[Depends(verify_trigger_api_key)]`
becomes `dependencies=[Depends(require_scope(f"trigger:{agent_id}"))]`.
`GET /agents` → `require_scope("read:registry")`. Phase 3 run-read routes →
`require_scope("read:runs")`. `GET /agent/proposals` →
`require_scope("read:proposals")`. Resolve route → `require_scope("resolve:proposals")`.
`/agent/chat` stays on customer JWT (`verify_customer_jwt`); it is not
re-gated by agent API keys.

`verify_trigger_api_key` stays in `auth.py` only as the fallback path
`require_scope` calls internally when validating the legacy single-key case
described above — not duplicated logic, one code path.

### Failure behavior

Missing header, unknown key, or key present without the required scope → 401
(matches today's behavior for missing/wrong key, so this is not a behavior
regression for legitimate callers, only a narrowing of what a given key can
do). Reason (`missing_key` / `unknown_key` / `insufficient_scope`) is logged
server-side via the existing `logger.warning` pattern in `auth.py`, never
returned in the response body (avoids leaking which scopes exist).

### Demo proof point

A key scoped only to `trigger:demand_forecast` calling
`/agents/inventory-reorder/trigger` gets rejected live — this is the
Phase 2 beat in the readiness plan's demo script.

## Testing

New `tests/test_identity.py`:

1. Master (`"*"`) credential can call every route
2. A credential scoped to one agent's trigger route is rejected on every
   other agent's trigger route
3. A credential with `read:registry` but not `resolve:proposals` is rejected
   on the resolve route
4. Unset `AGENT_API_KEYS` falls back to `AGENT_TRIGGER_API_KEY` as a master
   credential (migration path stays green)
5. Missing/empty `X-Agent-Api-Key` header → 401 on every gated route
6. `reload_config()` picks up a changed `AGENT_API_KEYS` value without a
   process restart (matches existing `reload_config` contract in
   `utils/config.py`)

## Out of scope

- Per-request rate limiting per credential → not requested, no rubric line
  depends on it
- Key issuance/rotation tooling (a CLI or endpoint to mint new credentials)
  → operationally useful later, not required for the hackathon demo; keys
  are hand-generated and placed in `AGENT_API_KEYS` for now
