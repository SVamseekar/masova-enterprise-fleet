# Changelog

All notable changes to **MaSoVa Enterprise Fleet** are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Fortified Enterprise Fleet: live agent registry, per-agent scoped identity, SHA-256 hash-chained run traces, Model Armor–lite chat guardrails
- Paris 24-store `DEMO_MODE` world, manager apply-on-approve, manager console at `GET /console`
- CI workflow (job name `test`)
- Gemini function-calling loops for specialist ops agents (`runtime/ops_llm.py`, `tools/ops_tools.py`)
- Tool ↔ HTTP ↔ platform map in `docs/CAPABILITY_MAP.md`
- Contract fixtures for order status, inventory, purchase orders, campaigns, and shifts
- Idempotency keys for draft purchase orders, campaigns, rotas, and price suggestions
- Canonical **ActionProposal** store and `GET`/`POST /agent/proposals*`
- Metrics: `runs_total`, `fallback_total`, `proposals_total`, `llm_error_total`
- Operator runbook and smoke checks
- Industry eval harness `tests/eval/test_industry_eval.py`

### Changed

- Equal quality bar for all eight agents (fallback, audit, signal gates)
- Operator budgets: `OPS_MAX_TOOL_CALLS`, `OPS_CONTEXT_CHARS`, `OPS_PREFER_LLM`, `OPS_LLM_MODEL`
- Public Markdown: production operator copy; ops manual rewritten as HACCP, labour, supplier, and equipment policies; runbooks use `$SERVICE_URL`

## [0.4.0] - 2026-08-08

### Added

- Shared **AgentRuntime** (policy, audit, fallbacks) for all eight agents
- HITL risk tiers: Read/Compute unrestricted; Propose = draft + manager notify; Execute never allowlisted
- Contract fixtures for order, menu, store, customer, and refund shapes
- GitHub Actions CI running `pytest` without a live model or platform
- `docs/AGENT_PLATFORM.md`
- `LLM_MODEL` / `LLM_API_KEY` configuration (public copy remains Gemini / Google ADK)

### Security

- Customer chat identity bound to the verified JWT
- Cancel, refund, and complaint copy states manager approval
- Alternate API-key chat scheme discarded

### Changed

- Ops agent public entries route through AgentRuntime with rule fallbacks
- `core/agent.py` is a shim over `agent.py`

## [0.3.0] - 2026-07-01

### Added

- JWT auth for `/agent/chat` and `AGENT_TRIGGER_API_KEY` for ops triggers
- Eight specialists (forecast, inventory, churn, review, shifts, kitchen, pricing) plus chat
- Redis sessions with in-memory fallback
- RabbitMQ consumer for low-rating reviews
- APScheduler jobs (configured timezone)

## [0.1.0] - 2026-02-17

### Added

- Initial service with Google ADK and Gemini
- Interactive chat and test scenarios
