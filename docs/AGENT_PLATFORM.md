# Agent Platform (v1)

Shared runtime for all MaSoVa support operators: support chat plus seven scheduled/event ops agents.

## Architecture

```text
Chat JWT / Trigger API key / APScheduler / RabbitMQ
        → FastAPI
        → AgentRuntime (policy, optional LLM tool loop, fallback, audit)
        → Read/Compute tools | Propose tools (DRAFT + manager notify)
```

### Ops LLM tool loops (agents 2–8)

When `LLM_API_KEY` / `GOOGLE_API_KEY` is set (and `OPS_PREFER_LLM` is not `false`):

```text
goal → context pack → multi-step GenAI function calling
    → allowlisted READ/COMPUTE/PROPOSE tools only
    → verify proposals (requires_approval, never EXECUTE)
    → audit (tools_used, proposal summaries, used_fallback)
```

Implementation:

| Module | Role |
|--------|------|
| `runtime/ops_llm.py` | `make_ops_llm_runner`, GenAI function-calling loop, scripted plan for tests |
| `tools/ops_tools.py` | Shared READ / COMPUTE / PROPOSE tools (`async` → `dict`) |
| `tools/ops_http.py` | Outbound `AGENT_TOKEN` HTTP helpers |
| `runtime/wrap.py` | Per-agent allowlists + `run_ops_agent` |

**Stack choice:** Ops use **Google GenAI function calling** for short-lived scheduled sessions (no long-lived ADK chat session). Customer **chat** continues on **Google ADK** `LlmAgent` + `Runner`. Both share HITL policy and audit via `AgentRuntime`.

**Cost control**

- Ops model: `OPS_LLM_MODEL` (falls back to `LLM_MODEL` / Gemini flash family).
- `prefer_llm` only when a key is present (`ops_prefer_llm()`).
- Dynamic pricing **pre-gate**: if no overload/underload signal, skip LLM and return quickly.
- On LLM failure: **rule fallback always runs** (never blank ops).

## HITL policy

| Tier | Behaviour |
|------|-----------|
| Read / Compute | Allowed automatically |
| Propose | Draft + manager notification; `requires_approval=true` |
| Execute | Never on agent allowlists (no silent price/PO/refund execution) |

Cancel, refund, and complaint tools always go through pending-approval backend endpoints.

Pricing agent **never** calls `PATCH /api/menu` — only manager notifications with capped % suggestions.

## Modules

| Path | Role |
|------|------|
| `runtime/models.py` | `AgentRunRequest`, `AgentRunResult`, `ActionProposal`, `RiskTier` |
| `runtime/policy.py` | Tool registry + allowlist enforcement |
| `runtime/audit.py` | Structured run logs (no secrets/PII dumps) |
| `runtime/agent_runtime.py` | Unified `run()` entry |
| `runtime/wrap.py` | Ops agent helpers + default allowlists |
| `runtime/ops_llm.py` | Ops multi-step tool loop |
| `tools/ops_tools.py` | Deterministic ops tools |
| `tools/backend_tools.py` | Customer chat tools (JWT-bound identity) |
| `agents/*_agent.py` | Thin public entry + rule fallback body |

## Agents

1. **Support chat** — `POST /agent/chat` (customer JWT); ADK tool loop
2. **Demand forecast** — cron 2am IST; COMPUTE WMA + optional LLM summary
3. **Inventory reorder** — every 6h; tool loop: low stock → draft PO → notify
4. **Churn prevention** — daily 10am IST; segment + draft campaign + notify
5. **Review response** — RabbitMQ + manual; order context + draft reply notify
6. **Shift optimisation** — Sunday 8pm IST; staff/forecast → draft shifts
7. **Kitchen coach** — nightly 11pm IST; metrics → brief notify
8. **Dynamic pricing** — every 30m 9–22 IST; suggest only; never patches prices

## Identity

- Customer chat: HS512 JWT (`JWT_SECRET`) verified in `auth.py`; tools use contextvars identity — never LLM-supplied customer IDs.
- Ops triggers: `AGENT_TRIGGER_API_KEY` header.
- Ops → platform backend: outbound `AGENT_TOKEN`.

## LLM configuration

| Variable | Purpose |
|----------|---------|
| `LLM_API_KEY` / `GOOGLE_API_KEY` | Provider key (prefer `LLM_API_KEY`) |
| `LLM_MODEL` | Chat / default model |
| `OPS_LLM_MODEL` | Cheaper ops model override |
| `OPS_PREFER_LLM` | `true`/`false` override; default = key present |

Product/docs describe Google ADK + Gemini. Do not document alternate provider brands in public materials.

## Fallback

If the LLM path fails, rule-based agents still draft proposals and notifications so operations continue offline from the model provider. `_runtime.used_fallback` and audit `used_fallback` record which path ran. Manager-facing text includes `rationale` when the LLM path produced proposals.

## Testing

- CI runs without live LLM or backend.
- Scripted tool plans exercise multi-step inventory + pricing golden paths.
- Policy tests assert EXECUTE tools never land on allowlists.

## Capability map

Full tool ↔ API ↔ service ↔ risk mapping: [CAPABILITY_MAP.md](./CAPABILITY_MAP.md).  
Optional live probes: [SMOKE.md](./SMOKE.md).

## Equal quality bar (all 8 agents)

| Bar | Requirement |
|-----|-------------|
| Entry | Public entry goes through `AgentRuntime` / `run_ops_agent` (chat via ADK + shared policy) |
| Tools | READ / COMPUTE / PROPOSE only; EXECUTE never allowlisted |
| Numbers | Stock, forecast, counts, prices only from READ/COMPUTE tools |
| Fallback | Rule path when `OPS_PREFER_LLM=false` or LLM raises |
| Idempotency | `runtime/idempotency.py` keys: agent+store+action+hour/date bucket on draft PO, campaign, shifts, price suggest |
| Audit | agent, trigger, store_id, tools_used, used_fallback, proposal summaries/rationale |
| Signal gate | Pricing: skip LLM when no overload/underload; inventory: skip when no low stock |
| Eval | Mocked golden paths in `tests/test_agents.py`, `tests/test_ops_llm_tools.py`, `tests/test_equal_agent_quality.py`, **`tests/eval/test_industry_eval.py`** |

### Industry eval harness (`tests/eval/`)

Scriptable / mocked (no live LLM or backend). Must stay green in CI:

1. Low stock → draft PO from tool quantities only  
2. Kitchen overload → price **suggest** only (no menu PATCH)  
3. Underload near close / no signal → skip suggestions  
4. 1★ review → draft response notify  
5. LLM raises → rule fallback still returns ok/draft  
6. Chat: spoofed customer id ignored (JWT identity binding)  
7. Cancel/refund copy mentions manager approval  
8. Idempotency: second draft same key is no-op  
9. Policy: EXECUTE tools rejected if requested

Agent 8 **never** calls `PATCH /api/menu` — only manager notifications with capped %.

## ActionProposal closed loop

Canonical model: `runtime/models.py` → `ActionProposal`  
Fields: `proposal_id`, `type`, `store_id`, `agent`, `summary`, `rationale`, `risk`,
`requires_approval=true`, `payload`, `status` (`PENDING|APPROVED|REJECTED|EXPIRED`),
`created_at`, `idempotency_key`, `resolution_note`, `resolved_at`.

| Step | Behaviour |
|------|-----------|
| Create | PROPOSE tools + runtime normalize → `proposal_store.save_proposal` (memory + JSONL under `data/proposals/`) |
| Notify | `notify_managers` includes `proposal_id`, summary, rationale in message/`data` |
| List | `GET /agent/proposals?storeId=&status=` (trigger API key) |
| Resolve | `POST /agent/proposals/{id}/resolve` `{status, note?}` records outcome only |

**Important:** Resolve on this service is **audit of manager decision**. Final business
execute (price PATCH, PO send, campaign live) still happens in platform UI/backend.

## Out of scope

- Auto-execution of prices, POs, or campaigns without a manager
- Multi-ERP ingest / custom model training
