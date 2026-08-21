# MaSoVa Enterprise Fleet

AI-powered customer support and ops agents for the MaSoVa restaurant platform, built with **Google ADK** and **Gemini**.

> **Disclosure:** This project incorporates pre-existing code from the author's private `masova-support` repository (development began 2026-02-18) as its foundation — the base agent runtime, the 8-agent fleet, and the proposal/approval model. This repository was created for the *All Things Agentic Hackathon* submission; the Fortified Enterprise Fleet work built during the submission period (Aug 3–31, 2026) — agent registry, per-agent identity, reasoning-chain audit, guardrails, and the EU-market demo layer — is new for this entry.

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Google ADK](https://img.shields.io/badge/Google-ADK-green.svg)](https://github.com/google/adk-python)
[![CI](https://img.shields.io/badge/CI-pytest-blue.svg)](.github/workflows/ci.yml)

## Overview

- **Support chat** (`POST /agent/chat`) — JWT-authenticated, tool-using ADK agent (orders, menu, loyalty, complaints, cancel/refund *requests*)
- **7 ops agents** — demand forecast, inventory reorder, churn, review response, shifts, kitchen coach, dynamic pricing
- **Human-in-the-loop** — agents **propose** (DRAFT + manager notify); they do not auto-execute prices, POs, or refunds
- **Shared AgentRuntime** — policy, audit logs, rule-based fallbacks when the model is unavailable

See [docs/AGENT_PLATFORM.md](docs/AGENT_PLATFORM.md) for architecture,  
[docs/CAPABILITY_MAP.md](docs/CAPABILITY_MAP.md) for tool ↔ platform APIs,  
[docs/RUNBOOK.md](docs/RUNBOOK.md) for operations, and  
[docs/SMOKE_CHECKLIST.md](docs/SMOKE_CHECKLIST.md) for live probes.

**Design:** industry-style vertical agents — secure identity, tool-grounded numbers, human approval proposals, rule fallbacks, contract-mapped APIs, audited runs, CI evals — not an omniscient autonomous platform brain.

## Quick start

### Prerequisites

- Python 3.9–3.12
- Gemini / Google GenAI API key
- Optional: Redis (sessions), RabbitMQ (review events), MaSoVa backend

### Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
cp config/env.example .env
# set LLM_API_KEY or GOOGLE_API_KEY, JWT_SECRET, AGENT_TRIGGER_API_KEY, AGENT_TOKEN, BACKEND_URL
```

### Run API

```bash
uvicorn src.masova_agent.main:app --host 0.0.0.0 --port 8000 --reload
```

- Health: `GET /health`
- Chat: `POST /agent/chat` with `Authorization: Bearer <customer-jwt>`
- Ops: `POST /agents/{name}/trigger` with `X-Agent-Api-Key: <AGENT_TRIGGER_API_KEY>`

### Tests

```bash
pytest tests/ -q
```

Unit tests mock HTTP and LLM; no Dell Redis/RabbitMQ/backend required. CI runs the same suite on pull requests.

### Docker

If a `Dockerfile` is present in the repo, build/run via your standard image flow. Prefer the uvicorn command above for local development.

## Project layout

```text
src/masova_agent/
  agent.py              # Support chat ADK agent (canonical entry)
  auth.py               # JWT + trigger API key
  main.py               # FastAPI app (+ proposals list/resolve)
  runtime/              # AgentRuntime, policy, audit, ops_llm, proposals, metrics
  agents/               # Ops agents (thin wrappers + rule fallbacks)
  tools/backend_tools.py
  tools/ops_tools.py    # Ops READ/COMPUTE/PROPOSE tools
  scheduler/            # APScheduler (shares FastAPI event loop)
tests/                  # unit + tests/eval industry harness
docs/                   # AGENT_PLATFORM, CAPABILITY_MAP, RUNBOOK, SMOKE*
.github/workflows/ci.yml
config/env.example
```

## Auth model

| Endpoint | Auth |
|----------|------|
| `/agent/chat` | Customer JWT (`JWT_SECRET`, HS512) — same secret as platform core-service |
| `/agents/*/trigger` | `AGENT_TRIGGER_API_KEY` |
| Outbound backend | `AGENT_TOKEN` (ops agents) or customer JWT (chat tools) |

Customer tools never trust LLM-supplied customer IDs; identity is bound from the verified JWT.

## License

Proprietary — MaSoVa.
