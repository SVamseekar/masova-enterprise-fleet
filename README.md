# MaSoVa Enterprise Fleet

A **Manager Copilot** for a multi-store restaurant fleet — one conversational, voice-capable agent that fans out to 7 specialist ops agents, grounds its answers in an internal ops manual via RAG, and puts every action behind human approval. Built with **Google ADK** and **Gemini**.

**[→ Landing page](docs/hackathon/landing.html)** — open in a browser for the visual overview of the governance model, the fleet, and the audit chain. Manager console: `GET /console` on a running API.

> **Disclosure:** This project incorporates pre-existing code from the author's private `masova-support` repository (development began 2026-02-18) as its foundation — the base agent runtime, the 8-agent fleet, and the proposal/approval model. This repository was created for the *All Things Agentic Hackathon* submission; the Fortified Enterprise Fleet work built during the submission period (Aug 3–31, 2026) — the Manager Copilot conductor agent, RAG-grounded ops-manual search, Gemini voice in/out, agent registry, per-agent identity, reasoning-chain audit, guardrails, and the live fleet console — is new for this entry.

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Google ADK](https://img.shields.io/badge/Google-ADK-green.svg)](https://github.com/google/adk-python)
[![CI](https://img.shields.io/badge/CI-pytest-blue.svg)](.github/workflows/ci.yml)

## Overview

- **Manager Copilot** (`POST /agent/manager/chat`) — the fleet's conversational front door. One conductor agent that can trigger any of the 7 ops agents, compare store performance, answer "what's our HACCP policy on X" from a real RAG index over `data/knowledge/`, and approve/reject pending proposals — all in one thread. Speaks and listens: Gemini transcribes voice input and can synthesize a spoken reply.
- **Live fleet console** (`GET /console`) — a manager-facing UI served from `src/masova_agent/static/console.html`: live agent registry, run history with reasoning traces, a SHA-256 hash-chain integrity badge over the run log, and the proposal approve/reject queue. No mocked data.
- **7 specialist ops agents** behind the Copilot — demand forecast, inventory reorder, churn, review response, shifts, kitchen coach, dynamic pricing.
- **Human-in-the-loop everywhere** — every agent **proposes** (DRAFT + manager notify); nothing auto-executes prices, POs, refunds, or campaigns.
- **Shared AgentRuntime** — policy, reasoning-chain audit, rule-based fallbacks when the model is unavailable.
- **Support chat** (`POST /agent/chat`) — the original customer-facing JWT-authenticated chat agent (orders, menu, loyalty, complaints, cancel/refund *requests*) still runs underneath, unchanged, as one tool the fleet talks to.

See [docs/AGENT_PLATFORM.md](docs/AGENT_PLATFORM.md) for architecture,
[docs/CAPABILITY_MAP.md](docs/CAPABILITY_MAP.md) for tool ↔ platform APIs,
[docs/RUNBOOK.md](docs/RUNBOOK.md) for operations, and
[docs/SMOKE_CHECKLIST.md](docs/SMOKE_CHECKLIST.md) for live probes.

**Design:** industry-style vertical agents — secure identity, tool-grounded numbers, human approval proposals, rule fallbacks, contract-mapped APIs, audited and hash-chained runs, CI evals — not an omniscient autonomous platform brain.

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
- Manager Copilot: `POST /agent/manager/chat` — fleet chat, RAG, voice in/out, proposal approve/reject
- Fleet console: `GET /console` on the service host
- Support chat: `POST /agent/chat` with `Authorization: Bearer <customer-jwt>`
- Ops: `POST /agents/{name}/trigger` with `X-Agent-Api-Key: <AGENT_TRIGGER_API_KEY>`

### Tests

```bash
pytest tests/ -q
```

Unit tests mock HTTP and the model; they do not require Redis, RabbitMQ, or a live platform backend. CI runs the same suite on pull requests.

### Docker

Build and run using the included `Dockerfile` via your standard image workflow (for example Cloud Run).

## Project layout

```text
src/masova_agent/                # FastAPI + agents (canonical product)
  static/console.html            # Live manager console (GET /console)
  agents/                        # Copilot + 7 specialist ops agents
  runtime/                       # HITL policy, audit, proposals, guardrails
  tools/                         # READ / COMPUTE / PROPOSE tools
  knowledge/                     # RAG over data/knowledge/
frontend/                        # Vite marketing / fleet showcase (not the console)
docs/                            # Product, runbook, Devpost copy
  hackathon/                     # Public landing page and fleet scenarios

scripts/                         # Seed, smoke, helpers
tests/                           # unit + eval harness
data/knowledge/                  # Ops manual sources for RAG
config/env.example
```

## Auth model

| Endpoint            | Auth                                                                      |
| ------------------- | ------------------------------------------------------------------------- |
| `/agent/chat`       | Customer JWT (`JWT_SECRET`, HS512) — same secret as platform core-service |
| `/agents/*/trigger` | `AGENT_TRIGGER_API_KEY`                                                   |
| Outbound backend    | `AGENT_TOKEN` (ops agents) or customer JWT (chat tools)                   |

Customer tools never trust LLM-supplied customer IDs; identity is bound from the verified JWT.

## License

Proprietary — MaSoVa.
