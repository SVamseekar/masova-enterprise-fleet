# Hackathon constraints — source of truth for every phase

Status: **locked** (review pass 2026-08-22). Every phase spec and plan inherits this file. If a phase doc contradicts this file, this file wins.

Track: All Things Agentic — **The Fortified Enterprise Fleet**.
Deadline: **31 Aug 2026, 17:00 PDT**. GCP credits request already submitted; approval pending.
Prize target: track win ($20k) with Grand Prize stretch; also select Startup Excellence if MaSoVa is incorporated. Max one prize per submission. Take all three bonus items (0.6 pts).

---

## 1. What judges must believe, in one sentence

A **Paris pizza-store operator** (24 sites, not one shop) runs eight specialised agents that read **store data**, propose **typed actions they are not allowed to execute**, a regional manager **approves**, and **queryable rows change** — on **Gemini 3.5 + Cloud Run**, with catalog, scoped identity, guardrails, calendar-aware signals, and a hash-chained trace.

Fleet size, calendar tags, and the $150 Gemini cap: [paris-fleet-scale.md](./2026-08-22-paris-fleet-scale.md).

## 2. The data question (do not host the MaSoVa platform)

The agents were designed against the MaSoVa restaurant-management backend (Dell `192.168.50.88`, commerce / logistics / payment, `shared-models`). That stack **will not be hosted on Google Cloud**. It is a private production system, it has confirmed API-contract drift, and it is out of rubric scope.

Judges still have to see **where the numbers come from**. "The agent said mozzarella is low" is a chatbot. "The agent called `list_low_stock`, the tool selected 3.1 L tomato base from SQLite row `INV-TOM-12L`, and that exact quantity is in the proposal payload" is an enterprise fleet.

### How data actually flows (demo / Cloud Run)

```
scripts/seed_demo_data.py
    → data/demo/masova_demo.sqlite     (real tables, Paris/DOM011, EUR cents)
         ↑  SELECT / INSERT / UPDATE
tools/ops_http.py  get_json / post_json     ⎤  DEMO_MODE=true
tools/backend_tools.py  _get / _post        ⎦  → services/demo_backend.py (SQL)
         ↑
tools/ops_tools.py, backend_tools.py        (unchanged call sites)
         ↑
AgentRuntime / ops LLM tool loop / ADK chat
         ↓
ActionProposal (PENDING) + ToolCallStep.result_summary
         ↓  manager Approve (this service, DEMO_MODE only)
SQLite row mutates (DRAFT PO → PENDING_APPROVAL, etc.)
```

`DEMO_MODE=true` is the **submission configuration**. It is not a fake-mode switch that returns canned dicts. Tools still call `_get`/`_post`; those helpers run SQL instead of `httpx` to Dell. Same agent code, same allowlists, same HITL policy.

When `DEMO_MODE=false` (local against the real MaSoVa backend on the LAN), nothing in this path changes except the last hop: HTTP to `BACKEND_URL`. That path is **not** what the video or Cloud Run shows.

### How we *show* it on camera (non-negotiable demo beats)

1. **Before.** `/console` → Store proof: mozzarella 6.2/10 kg, tomato 3.1/6 L, purchase order = none. Same numbers from `GET /agent/demo/tables/inventory`.
2. **Live run.** `/console` → Live run: stations light in order (scheduler → identity → `list_low_stock` → Open-Meteo → draft PO → HITL → waiting).
3. **Proposal.** Needs your OK card quotes those kg/L. Payload matches.
4. **Approve.** Manager clicks Approve.
5. **After.** Store proof: PO-DOM011-884 `PENDING_APPROVAL` with those lines. Canvas last station flips to approved. `GET /agent/runs/{id}` trace still contains 6.2 and 3.1. Menu price unchanged.

Chat / churn / reviews use the same pattern against `customers`, `orders`, `reviews`. One inventory golden path is the hero; a second agent (pricing or churn) is the orchestration beat.

### Honesty rules for seed data

- Field shapes come from `tests/fixtures/backend_contracts.py` **and** `docs/hackathon/EU_MARKET_SCENARIOS.md`, which were checked against platform `shared-models`. Prefer the EU scenario document when the fixture file still carries dual-tolerant legacy names (`unitPrice` vs `basePrice`, `reorderLevel` vs `minimumStock`).
- **24-store Paris fleet** in SQLite (see [paris-fleet-scale.md](./2026-08-22-paris-fleet-scale.md)). Hero close-up remains DOM011:

  | Field | Value | Meaning |
  |---|---|---|
  | `id` / `store_id` (flagship) | `68a1f2c9e4b0a1234567890a` | what agents and proposals use |
  | `code` (flagship) | `DOM011` | MaSoVa `DOM`+3 digits; UI label is 11e Oberkampf |

  Never use `DOM011` as `store_id`. Other stores have their own ObjectIds. A `store_id = 'DOM011'` in SQL is a bug.

  Why Paris: EU capital, GDPR + EU AI Act, restaurant-dense 11e. We model a **city operator of 24 MaSoVa stores** (Paris + inner ring), not a single shop and not every site in France.
- Seed once. Agent runs mutate the same file. Regenerating the DB between trigger and approve is cheating and will be visible if the before/after SQL doesn't match.

### What agents are allowed to write

HITL is unchanged: agents **never EXECUTE**. In DEMO_MODE:

| Tier | SQLite effect |
|---|---|
| READ / COMPUTE | SELECT only |
| PROPOSE | INSERT/UPDATE a **draft** row (`purchase_orders.status=DRAFT`, campaign `DRAFT`, shift roster `DRAFT`, price suggestion stored as a proposal only — no menu price UPDATE) |
| Manager APPROVED | `proposal_store.resolve` **also applies** the payload to SQLite (DRAFT → `PENDING_APPROVAL` / `APPROVED` per the platform enum for that resource). This is manager-triggered apply, not agent execute. |
| Manager REJECTED | draft row cancelled or left DRAFT with `rejectionReason`; no business-state advance |

On `DEMO_MODE=false`, resolve still only records the audit outcome (today's behaviour). The MaSoVa platform remains the executor. The video never claims otherwise.

### Data sources we use — and ones we do not

| Source | Used? | Why |
|---|---|---|
| Platform DB via API (`BACKEND_URL`) | Production / LAN only | Real MaSoVa. Not hosted on GCP. |
| SQLite (`DEMO_MODE`) | **Submission** | Same field shapes, queryable, shown in Store proof. |
| Direct user input | Yes | Manager Approve/Decline; customer chat. |
| Scheduler / clock | Yes | Cron/interval triggers. |
| Live weather HTTP | Yes | Open-Meteo for Paris (48.86, 2.35) as a READ tool — no API key, honest third-party fact. Pricing rain scenario uses this, not a made-up forecast string. |
| Env / secrets | Config only | Keys, `DEMO_MODE`. Not business facts. |
| Local random files | No | Restaurant truth is the store system, not a CSV on disk. |
| Web scraping | No | Unstable, often against TOS, not how a restaurant chain gets stock or orders. |
| Hardware sensors | No | We do not have a kitchen IoT fleet to show honestly. Kitchen Coach uses **aggregate station metrics already in the store DB**, not invented thermometers. |
| Voice / mic | Optional later | Old `masova-voice` stack stays out (too many local services). Gemini 3.5 can take audio if we add a thin mic path after Phases 1–6 are green — not required for the track. |

The in-repo console has three manager views: **Needs your OK**, **Live run** (station canvas of the real tool order), **Store proof** (before/after ledger).

## 3. LLM and cloud (credits pending)

- **Until GCP credits are approved:** iterate locally with any OpenAI-compatible endpoint via existing `LLM_API_KEY` / `LLM_MODEL` / LiteLlm. Do not spend personal GCP money. Do not deploy Cloud Run yet.
- **Submission deploy (after credits):** `LLM_MODEL=gemini-3.5-flash` (stable id, Gemini API or Vertex). Hackathon Stage 1 requires **Gemini 3.5 or newer**. `gemini-2.5-flash` in `config/env.example` is a disqualifier if it ships.
- **Never name the local iteration provider** in `docs/`, README, commit messages, API errors, logs shown on camera, or the demo video. Public story is Gemini + Google ADK. `CLAUDE.md` (gitignored) is the only place the iteration provider is named.
- Cloud Run: `DEMO_MODE=true`, `--max-instances=1` (SQLite is instance-local disk; more than one instance splits the demo DB), seed at container start if the file is missing, Secret Manager for secrets, min instances 0 after the video is in the can.
- **Gemini only on the focus store / live signals.** Fleet-wide scheduled sweeps use the rule fallback. See paris-fleet-scale.md § $150. 50k order rows are free; 24×8 Gemini loops every 30 minutes are not.

## 4. The product surface is this repo

Judges clone **one** repository. The live demo UI is `docs/hackathon/fleet-console-mockup.html` served by this FastAPI app and wired to live `/agents`, `/agent/proposals`, `/agent/runs`. The MaSoVa manager frontend (`AIAgentsSection.tsx`) is out of this submission.

Phase 6 is therefore: expiry + type filter **and** serving/wiring that console. Treating Phase 6 as "API already done, UI is another repo" fails the demo.

## 5. Bonus points (do all three)

1. Public write-up that states it was made for All Things Agentic Hackathon.
2. Social post with `#AllThingsAgenticHackathon`.
3. Second Google model: **Gemma** as the optional second pass of Model Armor–lite (regex always on; Gemma classifies ambiguous chat input when `GEMMA_MODEL` is set). Deterministic tests must pass with Gemma off.

## 6. Global engineering rules

- No hardcoded operational data. Display labels (agent name, category) may be authored. Store id/code above are **seed constants**, not per-request inventions.
- Agents propose; they do not execute. Demo apply-on-approve is a manager action.
- Tool functions stay `async def` → `dict`.
- Tests do not need live LLM or Dell. `DEMO_MODE` tests use temp SQLite.
- English only for submission materials.
- Dockerfile must include whatever the demo needs (seed script, static console, `src/`). `COPY src/` alone is not enough once Phase 5–6 land.

## 7. Phase order (unchanged, with the locked extras)

01 Registry → 02 Identity → 03 Reasoning trace → 04 Guardrails (+ optional Gemma) → 05 Demo SQLite + apply-on-approve → 06 Console wired in this repo → 07 Gemini 3.5 + Cloud Run after credits.

Do not start 07 Cloud Run spend until the credit code is on the billing account.
