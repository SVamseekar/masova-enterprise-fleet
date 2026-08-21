# Changelog

All notable changes to the MaSoVa Agent project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Ops multi-step GenAI tool loops (`runtime/ops_llm.py`, `tools/ops_tools.py`) for agents 2–8
- `docs/CAPABILITY_MAP.md` — full tool ↔ HTTP ↔ platform service map
- Expanded backend contract fixtures + tests (shared-models order statuses, inventory, PO, campaign, shifts)
- Idempotency keys for draft PO / campaign / shifts / price suggestions
- Canonical **ActionProposal** + local `proposal_store` + `GET/POST /agent/proposals*`
- Metrics hooks (`runs_total`, `fallback_total`, `proposals_total`, `llm_error_total`)
- `docs/RUNBOOK.md`, `docs/SMOKE.md`, `docs/SMOKE_CHECKLIST.md`, `scripts/smoke_backend.sh`
- Industry eval harness `tests/eval/test_industry_eval.py` (CI)

### Changed
- Equal quality bar documented for all 8 agents (fallback, audit, signal gates)
- Production env budgets: `OPS_MAX_TOOL_CALLS`, `OPS_CONTEXT_CHARS`, `OPS_PREFER_LLM`, `OPS_LLM_MODEL`

## [0.4.0] - 2026-08-08

### Added
- Shared **AgentRuntime** (policy, audit, fallbacks) for all 8 agents
- HITL risk tiers: Read/Compute free; Propose = draft + manager notify; Execute blocked
- Contract fixtures for backend order/menu/store/customer/refund shapes
- GitHub Actions CI workflow running `pytest` without live LLM/backend
- `docs/AGENT_PLATFORM.md` architecture notes
- Provider-agnostic `LLM_MODEL` / `LLM_API_KEY` config (docs remain Gemini/Google ADK)

### Security
- Customer chat JWT identity binding (main auth model)
- Friendly 403 denials and pending-approval wording for cancel/refund/complaint
- Security remediation branch absorbed (alternate API-key chat scheme discarded)

### Changed
- Ops agents public entry points route through AgentRuntime with rule fallbacks
- `core/agent.py` consolidated to shim over `agent.py`
- README/CHANGELOG accuracy for Docker, tests, and runtime

## [0.3.0] - 2026-07-01

### Added
- JWT auth for `/agent/chat` and `AGENT_TRIGGER_API_KEY` for ops triggers
- Eight ops agents (forecast, inventory, churn, review, shifts, kitchen, pricing) + chat
- Redis session service with in-memory fallback
- RabbitMQ consumer for low-rating reviews
- APScheduler jobs (Asia/Kolkata)

## [0.1.0] - 2026-02-17

### Added
- Initial project structure with Google ADK and Gemini
- Interactive chat and test scenarios
