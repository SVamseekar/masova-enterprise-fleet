# Design: MaSoVa contract alignment (hackathon-first)

Status: **draft for review** (2026-08-27)  
Track: All Things Agentic — Fortified Enterprise Fleet  
Inherits: [2026-08-22-hackathon-constraints.md](./2026-08-22-hackathon-constraints.md) (constraints win on conflict)

## 1. Purpose

Make the agent fleet’s HTTP paths, payloads, field shapes, and demo data **match real MaSoVa** so the submission is contract-honest — without hosting the MaSoVa JVM stack and without claiming drop-in for Toast/Square/other RMS.

**North star:** win the hackathon. MaSoVa alignment supports credibility; it must not break the DEMO_MODE golden path or burn the deadline on live platform plumbing.

## 2. Goals

- Tools, fixtures, and demo SQLite use **MaSoVa-correct** paths and entity field names for every surface agents touch.
- One ops HTTP exit (`ops_http`) for LLM tools and rule fallbacks (DEMO and live share the same call sites).
- DEMO_MODE remains the **submission and smoke** runtime (seeded SQLite + `/console`).
- HITL approve/reject works on demo without crashes; apply mutates SQLite with MaSoVa-correct statuses.
- Docs (CAPABILITY_MAP, fixtures) stop contradicting code and stop implying industry-universal APIs.
- **Data parity:** demo world volume and quality are on par with a real multi-store RMS (see §16), not a toy DB.
- **Agent quality:** responses and harnesses meet real-time AI-agent standards for restaurant ops (see §17).
- **No demo hardcoding:** numbers, proposals, and console proof come from tools/DB/runs — never canned kg/L or scripted cards (see §18).
- **Console presence:** `/console` must feel like a live agentic control surface for restaurant ops — not a flat mock dashboard (see §19).

## 3. Non-goals

- Hosting full MaSoVa (gateway + microservices) on GCP for the hackathon.
- Live Dell/LAN smoke as a submission gate.
- Live manager-JWT ops auth overhaul as a **blocker** for submit (document the real model; implement when free).
- Live approve → MaSoVa execute callbacks as a submit requirement.
- Toast / Square / generic RMS adapters or “drop into your RMS” product claims.
- Rewriting agent jobs or replacing `/console` with the MaSoVa manager frontend (we keep one HTML console in this repo; we **may redesign** it — see §19).

## 4. Architecture (unchanged shape, corrected contract)

```
Agents + tools
    → ops_http / backend_tools
        → DEMO_MODE? demo_backend (SQLite, MaSoVa-shaped)
        → else? httpx → BACKEND_URL (MaSoVa gateway)
    → ActionProposal + run trace
    → Manager resolve (DEMO: apply to SQLite)
```

No new adapter framework. Alignment is **direct MaSoVa contract** in tools + demo, not a portable canonical layer.

## 5. Auth

| Mode | Behavior |
|------|----------|
| DEMO | Local fake tokens; no gateway. Smoke/CI/video use this. |
| Live (post-hackathon / optional LAN) | Ops must use a MaSoVa-accepted **MANAGER** (or ASSISTANT_MANAGER) JWT (`userType`, `storeId`, shared `JWT_SECRET`). Chat keeps customer JWT. `AGENT_TOKEN` is not a real MaSoVa gateway credential. |

Hackathon deliverable: document this clearly; do not block submit on minting live ops JWTs.

## 6. Path and payload alignment

### 6.1 Must fix (agents call these today)

| Fleet today | MaSoVa reality | Action |
|-------------|----------------|--------|
| `GET /api/analytics/forecast` | `GET /api/bi?type=demand-forecast` (or `sales-forecast`) | Retarget tools + demo routes |
| `GET /api/analytics/products` | `GET /api/analytics?type=top-products` | Retarget |
| `GET /api/analytics/orders` | `GET /api/orders/analytics?type=…` | Retarget |
| `POST /api/purchase-orders/auto-generate` **with draft body** | Auto-generate is **trigger-only** (no body) | Agent drafts via `POST /api/purchase-orders` with `status=DRAFT` (or equivalent create). Keep auto-generate only if used as a true trigger. |
| Shift bulk: array vs `{storeId, shifts}` split | Match `POST /api/shifts/bulk` controller contract | One shape everywhere |
| Forecast write: per-row vs batch split | Match intelligence/BI write surface if any; else store forecast only in demo tables that mirror agreed read shape | One write shape |
| CAPABILITY_MAP `POST /api/complaints`, `/api/refunds` | Code: `/api/reviews/complaints`, `/api/payments/refund/request` | Docs follow code + MaSoVa |

### 6.2 Keep (already aligned enough)

- `GET /api/inventory?lowStock=true`
- `GET /api/stores`, `GET /api/orders`, `GET /api/customers`, `GET /api/users`, `POST /api/notifications`
- `POST /api/orders/{id}/cancel-request`
- `POST /api/payments/refund/request` (path)

## 7. Field alignment (drop lying dual-tolerance)

Prefer MaSoVa entity names; keep dual-read **only** where MaSoVa itself dual-emits (e.g. store `operatingConfig` write helper).

| Stop preferring / inventing | Use |
|-----------------------------|-----|
| `OrderItem.unitPrice` | `price` |
| Flat `loyaltyPoints` / `totalOrders` | `loyaltyInfo.*`, `orderStats.*` |
| `preferredSupplierId` | `primarySupplierId` |
| Inventory `name` / `reorderLevel` | `itemName` / `minimumStock` |
| Refund `APPROVED`, `refundId` | Real statuses; `razorpayRefundId` where applicable |
| `OrderStatus.PENDING` | Start from `RECEIVED` (platform enum) |
| Campaign `CHURNED_HIGH_VALUE` / `customerIds` | Real `CustomerSegment` + `targetUserIds` |
| Shift status `DRAFT` if not in platform | MaSoVa shift statuses (`SCHEDULED`, `PENDING_APPROVAL`, …) — map demo apply accordingly |

Demo seed + `demo_backend` responses must emit the **canonical** MaSoVa names first.

## 8. HTTP unification

- All ops rule agents call `ops_http.get_json` / `post_json` only (no raw `httpx` to `BACKEND_URL`).
- Inventory already mostly does this; migrate demand, churn, shift, kitchen, pricing, review rule paths.
- Ensures `DEMO_MODE` works when Gemini is capped / rule fallback runs (hackathon $150 Gemini budget).

## 9. HITL apply

| Mode | Approve | Reject |
|------|---------|--------|
| DEMO | Mutate SQLite with MaSoVa-correct status transitions (e.g. PO → `PENDING_APPROVAL`) | Must not ImportError; cancel draft / record reason per existing design |
| Live | Out of submit scope: audit-only OK; real execute later | Audit-only |

**P0:** restore `apply_rejected_proposal` or remove the import/call in `main.py` so Decline does not crash the console demo.

## 10. Phased delivery (hackathon-ordered)

0. **Unbreak** — reject-apply import/call consistency.  
1. **Contract truth** — fixtures, CAPABILITY_MAP, demo shapes → MaSoVa entities.  
2. **Auth docs + demo behavior** — live JWT model documented; demo fakes stay demo-only.  
3. **Path/payload fixes** in `ops_tools`, `backend_tools`, `demo_backend`, agents.  
4. **Unify** rule agents onto `ops_http`.  
5. **Demo HITL apply** status/field parity (live execute deferred).  
6. **Data + anti-hardcode** — enforce Paris fleet volumes (§16); strip console/static fallbacks that invent mozzarella/tomato figures (§18).  
7. **Agent harness quality** — tool-grounded proposals, real traces, no canned narrative when live APIs fail (§17).  
8. **Verify** — unit/contract tests + **demo smoke only** (inventory golden path + one second agent). Assert seed volume gates + “no static proof numbers.” No hosted MaSoVa required.

## 11. Change vs freeze

**Freeze:** AgentRuntime, policy (no EXECUTE), registry, identity, traces, guardrails, `/console`, eight agent jobs, DEMO_MODE submission config, public Gemini story, bonus write-up/social/Gemma.

**Change:** reject path, MaSoVa path/field honesty in tools+demo+docs, `ops_http` unification, PO draft semantics, demo smoke, seed volume/quality gates, remove hardcoded console demo numbers, harden agent harness quality for RMS.

**Do not before submit:** full MaSoVa on GCP, live ops JWT as blocker, live execute-on-approve, multi-RMS adapters, inventing a new agent product surface.

## 12. Testing and errors

- Unit tests mock HTTP; DEMO tests use temp SQLite.  
- Contract fixtures derived from MaSoVa `shared-models` / controllers (update `tests/fixtures/backend_contracts.py` + CAPABILITY_MAP).  
- Smoke checklist = DEMO_MODE only (seed → trigger → proposal → approve → table proof).  
- Tool/HTTP failures: structured error dicts; never raw stack traces to console/chat.  
- Rule fallback must succeed on demo without LLM.

## 13. Hackathon win test

Rehearsed demo:

1. `/console` Store proof — low stock numbers **fetched from APIs/SQLite**, not HTML defaults.  
2. Live run — inventory agent stations / real tool order from the run store.  
3. Needs your OK — proposal payload **equals** tool/`list_low_stock` quantities (same strings in trace).  
4. Approve — PO (or equivalent) status advances in Store proof from DB.  
5. Run trace still contains the same quantities.  
6. Optional second beat (pricing or churn) for orchestration — also tool-grounded.

All under `DEMO_MODE=true`. English submission materials. No alternate-provider names in public docs/video.

## 14. Success criteria

- [ ] Decline proposal does not 500.  
- [ ] Demo inventory golden path green end-to-end.  
- [ ] No agent rule path bypasses `ops_http`.  
- [ ] Analytics/BI/orders-analytics and PO draft calls match MaSoVa semantics in code + demo.  
- [ ] Fixtures/docs use MaSoVa field names; CAPABILITY_MAP matches code.  
- [ ] CI green without Dell/MaSoVa hosting.  
- [ ] Video/rehearsal uses only demo data.  
- [ ] Seed volume gates pass (stores/orders/inventory per §16 / paris-fleet-scale).  
- [ ] Console has **no** static mozzarella/tomato/kg fallbacks that can appear on camera.  
- [ ] Proposal rationale cites tool results; empty-tool runs do not invent stock figures.

## 15. Open points (resolved by this spec)

- Generic RMS / adapter layer: **rejected** for this effort.  
- Smoke target: **demo only**.  
- Complete live MaSoVa wiring: **contract target**, not submission runtime.  
- Vector DB as primary ops store: **rejected** — structured tools + SQL are the correct advanced pattern for RMS numbers.  
- Hardcoded demo numbers: **rejected** absolutely.

## 16. Data volume and quality (real-RMS bar)

Seeded DEMO data must feel like an operator RMS, not a handful of rows. Locked targets inherit [paris-fleet-scale.md](./2026-08-22-paris-fleet-scale.md):

| Bar | Requirement |
|-----|-------------|
| Fleet | 24 stores with **distinct** volume bands (large/medium/small), not 24 clones |
| Orders | ~45k–55k over 14 days; ≥3 distinct daily-volume clusters in SQL checks |
| Inventory | 24 × ~48 SKUs; hero low-stock only where seeded — other stores different posture |
| Customers / staff / shifts / reviews | Per paris-fleet-scale locked counts |
| Quality | MaSoVa-shaped fields; calendar tags drive different agent outcomes |
| Honesty | Seed is synthetic but **queryable and consistent**; regenerating mid-demo is cheating |
| **No hardcoding** | Zero operational numbers in UI/agents; only seed script may define world constants |

**Gap to close:** CI assertions on counts + band diversity after contract renames. Fix the seed if thin — never fake volume in the UI.

## 17. Agent harness and response quality (RMS AI bar)

| Bar | Requirement |
|-----|-------------|
| Grounding | Every number comes from a tool result or COMPUTE over tool inputs |
| HITL | Propose only; manager approve is the mutation |
| Fallback | Rule path produces the same class of proposal from the same SQL |
| Structure | Tool loop → typed `ActionProposal` → audit/trace; structured errors |
| Domain voice | RMS language, not generic chatbot filler |
| Eval | Industry eval harness catches quality regressions in CI |

## 18. No hardcoding (absolute)

**Forbidden:** canned kg/L, static proposal cards, inventing counts on empty tools, SQLite edits between before/after, console fallbacks that invent a ledger.

**Allowed:** seed constants in `seed_demo_data.py` only; authored agent display labels.

**Required:** Grok-like UI binds only to live APIs; smoke asserts proposal qty ⊆ inventory query; CI fails on known canned inventory strings in frontend.

## 19. Console UX — Grok-like **MaSoVa AI** interface

**Product name in UI:** **MaSoVa AI** (not “Fleet” / not xAI branding).

**Problem:** Current `fleet-console-mockup.html` reads as an admin/ops dashboard, not a live agentic product.

**Chosen direction:** chat-first Grok-like shell — conversational, streaming feel, minimal chrome — for restaurant fleet ops.

**Constraints (locked)**
- One self-contained HTML (or minimal assets) served by this FastAPI app at `/console` (or `/` redirect).
- Wired to live `/agents`, `/agent/proposals`, `/agent/runs`, demo tables — **no invented ledger numbers**.
- Manager Approve/Decline **in-thread**; inventory golden path is the hero video beat.
- Avoid purple-glow / cream-terracotta / acid-green AI-slop defaults.

**Locked interaction model**

| UI element | Behavior | API |
|------------|----------|-----|
| Chip **Run inventory** | Deterministic trigger for focus store; thread shows tool steps then proposal card | `POST /agents/inventory_reorder/trigger` → poll `GET /agent/runs/{id}` → `GET /agent/proposals` |
| Chip **Pricing signal** | Same for pricing agent; message if no signal | `POST /agents/dynamic_pricing/trigger` → runs/proposals |
| Chip **Store proof** | Read-only proof card in thread (before/after Approve) | `GET /agent/demo/tables/...` (inventory + POs for focus store) |
| Free-text composer | Ask / status; may map to trigger or explain — never invent qty | Existing chat or thin router; numbers only from tools |
| Inline **Needs your OK** card | Approve / Decline | `POST /agent/proposals/{id}/resolve` |
| Agent rail | **All 8 agents** live from registry + pending/run status | `GET /agents`, proposal list, optional runs |

**Success:** First 10 seconds of the video read as talking to **MaSoVa AI**, watching grounded tool steps and approving a real proposal — not scanning an admin table.

## 20. Advanced agentic data plane (research → what we advance)

What “advanced” means in agentic systems today is **not** “swap SQLite for a vector DB.” For restaurant ops numbers, industry practice favors a **structured semantic/tool layer over governed data**, with separate memory kinds and forensic audit — not RAG as the source of truth for stock or money.

| Industry pattern | What we advance (still on SQLite + tools) |
|------------------|-------------------------------------------|
| Typed tools / semantic answering tier (not free-text RAG for metrics) | Keep typed ops tools; strengthen return shape: `ok`, `as_of`, entity ids, quantities from SQL |
| Fresh operational facts | Every tool read = live query; no cached fake UI state |
| Separate memory kinds | (1) SQLite = business facts (2) run/proposal stores = execution audit (3) chat session = conversation only — never collapse |
| Hash-chained / immutable audit | Keep reasoning traces; tool steps must store ids+qty from SQL in `result_summary` |
| Policy + least privilege | Existing READ/COMPUTE/PROPOSE; EXECUTE blocked; scoped keys |
| Idempotency | Proposal `idempotency_key`; safe demo writes |
| Provenance | Proposals carry `evidence[]`: `{tool, row_id, field, value}` copied from tool output — LLM must not author those numbers alone |
| Real volume | Enforce §16 fleet scale |
| Optional RAG | Only for unstructured text (e.g. review body) if ever — **never** for SKU qty |

**SQLite is advanced enough when** it is a transactional RMS store, tools are the semantic layer, audits are chained, and the UI never bypasses tools. Postgres/Dynamo/TiDB upgrades are out of scope before submit.

**Advance checklist**
- [ ] Tool responses include `as_of` + entity ids from SQL  
- [ ] Proposals include `evidence[]` linked to those ids  
- [ ] Grok UI renders evidence from APIs only  
- [ ] Seed volume CI gates  
- [ ] No canned strings in frontend  
- [ ] Trace ids/qty match Store proof  

## 21. Industry-aligned tech choices (what top companies converge on)

Stakeholder requirement: choose tech the way top agentic platforms do — robust and apt, not novelty for its own sake.

### What Google / OpenAI / Anthropic / Microsoft converge on

| Capability | Industry pattern | Examples |
|------------|------------------|----------|
| Agent runtime | Framework with agents + tools + sessions + traces | Google **ADK**, OpenAI **Agents SDK**, Microsoft **Agent Framework**, Amazon Bedrock Agents |
| Model | Frontier model via first-party stack for the contest | Hackathon: **Gemini 3.5** on ADK (required). Local iteration may use LiteLLM; public story stays Gemini |
| Tools | Typed function/tools against **systems of record**; progressive tool discovery at scale | OpenAI/Anthropic tool schemas; Anthropic **MCP**; ADK `BaseTool` |
| Grounding for ops facts | **Structured tool results** (and search grounding for web) — not inventing numbers | ADK Google Search grounding for web; **SQL/API tools** for RMS |
| Orchestration | Specialist agents + manager / handoffs / graphs | OpenAI handoffs & agents-as-tools; ADK 2.0 **workflow graphs**; multi-agent registry |
| Human oversight | Explicit approval interrupts before risky side effects | OpenAI human approval; our HITL proposals (PROPOSE ≠ EXECUTE) |
| Guardrails | Input/output/(tool) checks | OpenAI guardrails; our Model Armor–lite + policy tiers |
| Observability | First-class run traces (tool spans, not just chat logs) | OpenAI tracing; our hash-chained run store |
| Memory split | Session/chat ≠ business data ≠ audit | Microsoft context providers; TiDB/AWS “unified but typed” data stories |
| Integration standard (later) | MCP / OpenAPI tool servers | Anthropic MCP; Microsoft MCP; OpenAI Hosted MCP |

### Apt choices for **this** repo

| Layer | Choose | Why (industry-aligned) | When |
|-------|--------|------------------------|------|
| Runtime | Stay on **Google ADK** + Gemini for submit | Contest + Google’s agent stack; already in repo | Now |
| Ops truth | **Typed tools → transactional store** (DEMO: SQLite stand-in for MaSoVa) | Same pattern as tool→CRM/ERP at OpenAI/MS/Google; SQLite is the stand-in, not a different architecture | Now |
| Vector DB | **Do not** make it the ops source of truth | Big tech uses vectors for docs/memory retrieval, not for inventory qty | Now (reject) |
| Audit | Keep/strengthen **run traces + proposal store** | Matches Agents SDK tracing / enterprise audit expectations | Now |
| HITL | Keep **propose → manager approve** | Matches human-approval / HITL patterns | Now |
| UI | **Grok-like chat shell** over live APIs | Chat-primary agent UX; still tool-grounded | Now |
| Contract | Align tools/demo to **MaSoVa** shapes | Real SoR contract | Now |
| MCP | Optional **later** as tool-server façade over `ops_tools` | Industry integration standard — not required to win if tools already typed | Post-submit |
| ADK 2.0 graphs | Optional **later** for deterministic multi-step runs | Google’s direction for reliability | Post-submit if stable & time |
| Cloud DB | Postgres/Cloud SQL **later** if leaving single-instance DEMO | Scale-out; same tools, swap connection | Post-win / production |
| Live MaSoVa | Manager JWT + real paths | Production SoR | When hosting/credits allow |

### Explicit non-choices (not what top companies do for RMS agents)

- Replacing the tool layer with “just RAG over CSVs.”
- Hardcoded demo numbers in the UI.
- Claiming multi-POS drop-in without MCP/OpenAPI adapters and real APIs.
- Switching off ADK to chase another framework mid-hackathon (destroys Gemini/track alignment).

**Principle:** Match **patterns** (tools, HITL, traces, split memory, Gemini/ADK), not every vendor product name. SQLite in DEMO is an implementation of the transactional SoR pattern — advanced when provenance and volume are real, weak only when the UI invents data.
