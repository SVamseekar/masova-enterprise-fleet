# Documentation

Operator and architecture documentation for MaSoVa Enterprise Fleet.

| Path | Contents |
| --- | --- |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Gemini, FastAPI, data stores, `GET /console` |
| [AGENT_PLATFORM.md](AGENT_PLATFORM.md) | Copilot, specialists, HITL policy |
| [CAPABILITY_MAP.md](CAPABILITY_MAP.md) | Tools vs platform APIs |
| [RUNBOOK.md](RUNBOOK.md) | Incidents, Redis, RabbitMQ, model outage |
| [SMOKE.md](SMOKE.md) / [SMOKE_CHECKLIST.md](SMOKE_CHECKLIST.md) | Health and HITL probes |
| [DEVPOST_SUBMISSION.md](DEVPOST_SUBMISSION.md) | Product narrative |
| [DEVPOST_REQUIREMENTS.md](DEVPOST_REQUIREMENTS.md) | Track rules and originality disclosure |
| [hackathon/landing.html](hackathon/landing.html) | Public landing page |
| [hackathon/EU_MARKET_SCENARIOS.md](hackathon/EU_MARKET_SCENARIOS.md) | Paris fleet proposal scenarios |

The live manager console is not a document. It is `src/masova_agent/static/console.html`, served at `GET /console`.

Ops policies used by RAG live under `data/knowledge/` (HACCP, labour, suppliers, equipment).
