# Docs (hackathon GitHub surface)

Only these files are meant to be in the public repo. Internal plans, QA notes, and mockups stay local (see `.gitignore`).

| Path | What judges / clones get |
| --- | --- |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Gemini ↔ API ↔ SQLite ↔ `GET /console` |
| [AGENT_PLATFORM.md](AGENT_PLATFORM.md) | Copilot, specialists, HITL |
| [CAPABILITY_MAP.md](CAPABILITY_MAP.md) | Tools vs platform APIs |
| [RUNBOOK.md](RUNBOOK.md) / [SMOKE.md](SMOKE.md) / [SMOKE_CHECKLIST.md](SMOKE_CHECKLIST.md) | Run and probe |
| [DEVPOST_SUBMISSION.md](DEVPOST_SUBMISSION.md) | Devpost text |
| [DEVPOST_REQUIREMENTS.md](DEVPOST_REQUIREMENTS.md) | Track rules and originality disclosure |
| [hackathon/landing.html](hackathon/landing.html) | Visual overview |
| [hackathon/EU_MARKET_SCENARIOS.md](hackathon/EU_MARKET_SCENARIOS.md) | Paris fleet demo world |

The live manager console is **not** documentation. It is `src/masova_agent/static/console.html`, served at `GET /console`.
