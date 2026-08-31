# Devpost submission text — MaSoVa Enterprise Fleet

Track: **The Fortified Enterprise Fleet**

---

## Inspiration

Restaurant chains don't have one workflow problem — they have eight, running
in parallel, at every store, every day: demand keeps shifting, inventory runs
low, reviews pile up unanswered, shifts need rebalancing, prices drift out of
sync with demand. A single chatbot can't safely touch all of that, because
"safely" is the whole problem: an agent that can silently issue a refund,
cut a purchase order, or reprice a menu is a liability, not a feature. We
wanted a fleet of specialists that could actually do the work, behind a
single conversational front door, without ever taking an action a human
didn't approve.

## What it does

**MaSoVa Enterprise Fleet** is a Manager Copilot for a multi-store
restaurant chain. One conversational, voice-capable Gemini agent sits in
front of seven specialist ops agents — demand forecasting, inventory
reorder, churn prevention, review response, shift optimisation, kitchen
coaching, and dynamic pricing — and a legacy customer-support chat agent.
The manager asks in plain language ("how's the SoHo store doing this
week?", "run inventory for all stores", "what's our HACCP policy on raw
poultry?") and the Copilot:

- fans out to the right specialist agent(s) and reports back,
- answers ops-manual questions grounded in a real RAG index (no
  hallucinated policy),
- compares store performance across the fleet,
- and surfaces every agent action as a **proposal** — draft purchase order,
  draft campaign, draft shift roster, price suggestion — that a manager
  must explicitly approve or reject before anything touches the real
  system.

Nothing executes automatically. Every agent's tool access is tiered:
**Read/Compute** runs freely, **Propose** drafts and notifies, **Execute**
does not exist on any agent's allowlist. A live fleet console shows the
agent registry, a hash-chained run history with full reasoning traces, and
the approve/reject queue — all fetched live from the running service, no
mocked data.

## How we built it

- **Google ADK** for the customer support chat agent (`LlmAgent` + `Runner`,
  session-based).
- **Gemini function calling** for the seven ops agents — short-lived,
  per-trigger tool loops rather than long-running chat sessions, since
  scheduled/event-driven ops work doesn't need conversational memory.
- **Gemini `text-embedding-004`** for RAG over the ops manual, with a
  lexical-search fallback so a missing key or embedding outage never breaks
  the copilot.
- **APScheduler** running inside the FastAPI event loop for the six
  time-based agents (cron/interval), plus RabbitMQ for review-triggered
  runs.
- **A shared `AgentRuntime`** enforcing the HITL policy tier, structured
  audit logging, and rule-based fallbacks — if a Gemini call fails for any
  reason, the affected agent degrades to a deterministic rule path instead
  of surfacing a raw error or going silent.
- **Guardrails** on the one path that takes free-text human input (chat):
  regex/heuristic prompt-injection screening, Luhn-validated card-number
  redaction, and email redaction, with an optional Gemma-model classifier as
  a second opinion.
- **Per-agent scoped identity** (`AGENT_API_KEYS`) instead of one shared
  trigger secret, so a leaked credential for one agent doesn't grant access
  to the rest of the fleet.
- **A SHA-256 hash-chained run log** — every agent run's record includes the
  hash of the previous record, so the audit trail is tamper-evident, not
  just logged.
- **Cloud Run** hosting the FastAPI service.

## Challenges we ran into

- Keeping the LLM path and the rule-fallback path at genuine parity — every
  ops agent had to produce the same structured `ActionProposal` shape
  whether Gemini answered or the fallback fired, so the console and the
  approval queue never have to special-case which path ran.
- Idempotency under real concurrency: an early version of the rule-fallback
  path for inventory reorder had no dedup guard and could flood the
  approval queue with duplicate purchase orders on repeated triggers — fixed
  with a `check_or_claim` guard keyed on store/supplier/hour, matching the
  guard the LLM tool-loop path already had.
- Test isolation: our test suite's mocked agent runs were writing directly
  into the same on-disk proposal/run JSONL files the live console reads
  from, silently polluting demo data with mock store IDs on every `pytest`
  run. Fixed with an autouse fixture that isolates test runs into a
  temporary directory.
- Making rate limiting tier-aware: agent trigger routes need a higher
  request budget than default API routes, but the middleware wasn't passing
  route tier through to the limiter, so ops triggers were getting throttled
  at the same ceiling as everything else.

## Accomplishments that we're proud of

- A genuinely tiered permission model enforced in code, not just described
  in docs — Execute-tier tools don't exist for any agent, so there's no
  runtime check to forget.
- A tamper-evident audit trail (hash chain) over every agent action, not
  just a log line.
- Rule-based fallbacks with real parity to the LLM path, verified by a full
  pytest suite that exercises both.
- A live console with zero mocked data — every number, badge, and proposal
  card is fetched from the running service.

## What we learned

Multi-agent systems earn trust through constraints, not capability — the
interesting engineering here wasn't getting Gemini to draft a purchase
order, it was making sure it's structurally impossible for that draft to
become a real purchase order without a human in the loop.

## What's next for MaSoVa Enterprise Fleet

Wiring the landing page's demo surfaces to the live backend (currently an
intentional self-contained simulator for demo purposes), building the
manager-facing approve/reject panel as a first-class UI rather than
console-embedded, and extending the reasoning-chain audit to cover the ADK
support-chat agent's tool calls the same way the ops agents' are already
covered.

---

## Built with

Python, FastAPI, Google ADK, Gemini API, Google GenAI SDK (function
calling), Gemini `text-embedding-004`, Google Cloud Run, APScheduler,
RabbitMQ, Redis, SQLite (demo data layer), pytest, GitHub Actions.
