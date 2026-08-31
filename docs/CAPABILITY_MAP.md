# Capability map — tools and platform APIs

This is the contract for what MaSoVa Enterprise Fleet may call. Every customer-chat and ops tool is listed with **risk tier**, HTTP surface, and owning platform service. If a capability is not in this file, it is out of scope until it is added here and allowlisted in `runtime/policy.py`.

Numbers that appear in the console (stock, covers, prices, ticket times) must come from **READ** or **COMPUTE** tools. Policy text comes from RAG over `data/knowledge/`. Agents never EXECUTE commerce writes.

---

## Authentication

| Caller | Credential |
|--------|------------|
| Customer chat tools (`backend_tools`) | Customer JWT (`Authorization: Bearer`) |
| Ops tools (`ops_tools` / `ops_http`) | `AGENT_TOKEN` |
| Manual agent triggers and proposal API | `AGENT_TRIGGER_API_KEY` or scoped `AGENT_API_KEYS` |

Customer tools **never** trust a model-supplied customer id. Identity is taken from the verified JWT.

When `DEMO_MODE=true`, the same HTTP shapes are served from the synthetic Paris fleet. When `DEMO_MODE` is off, `BACKEND_URL` is the MaSoVa platform gateway.

---

## HTTP exit points

| Module | Role |
|--------|------|
| `tools/backend_tools.py` | Customer chat → platform |
| `tools/ops_http.py` + `tools/ops_tools.py` | Specialist tool loop → platform |
| `agents/*_agent.py` (rule fallback) | Same paths via `httpx` if the model path is down |

Prefer tools for new work so allowlists and audit stay in one place.

---

## Risk tiers

Defined in `runtime/policy.py`.

| Tier | Meaning |
|------|---------|
| READ | Fetch data only |
| COMPUTE | Derive a signal from tool inputs (no network write) |
| PROPOSE | Draft + notify; `requires_approval=true`; no silent execute |
| EXECUTE | **Blocked** — never on any agent allowlist |

Platform domains: **core** · **commerce** · **payment** · **logistics** · **intelligence**

---

## Agent 1 — Support chat (Google ADK)

Intents implemented today (no checkout):

| Intent | Tools | Notes |
|--------|-------|-------|
| Order status | `get_order_status` | Ownership enforced by the platform |
| Menu browse | `get_menu_items` | Filter cuisine/category on the client |
| Store hours | `get_store_hours` | Nested `operatingConfig` or flat times |
| Loyalty | `get_loyalty_points` | Identity from JWT only |
| Wait time | `get_store_wait_time` | Heuristic from active orders if no ETA field |
| Complaint | `submit_complaint` | Pending manager handling |
| Cancel | `cancel_order` | Cancel **request**; manager approval |
| Refund | `request_refund` | Refund **request**; manager approval |

| Tool | Risk | Method + path | Platform | Notes |
|------|------|---------------|----------|-------|
| `get_order_status` | READ | `GET /api/orders/{id}` | commerce | Status enum from shared models |
| `get_menu_items` | READ | `GET /api/menu?storeId=&available=` | commerce / core | Page or list |
| `get_store_hours` | READ | `GET /api/stores/{id}` | core | Nested vs flat hours |
| `get_loyalty_points` | READ | `GET /api/customers/{id}` | core / commerce | Never a model-supplied customer id |
| `get_store_wait_time` | READ | `GET /api/orders?storeId=&status=` | commerce | Active-order count heuristic |
| `submit_complaint` | PROPOSE | `POST /api/reviews/complaints` | core | Ticket |
| `cancel_order` | PROPOSE | `POST /api/orders/{id}/cancel-request` | commerce | Not instant cancel |
| `request_refund` | PROPOSE | `POST /api/payments/refund/request` | payment | Pending approval |

**Not in this product**

| Capability | Status |
|------------|--------|
| Place order / checkout | Out of scope |
| Live delivery map | Future (logistics) |
| Payment capture / card update | Out of scope |
| Instant cancel / execute refund | Never (EXECUTE) |

---

## Manager Copilot — fleet chat

`POST /agent/manager/chat`. Fans out to specialists, answers policy questions from the ops manual, and is the approve/reject surface for HITL proposals. Voice in (Gemini transcription) and optional voice out (Gemini TTS).

| Tool | Risk | Method + path | Platform | Notes |
|------|------|---------------|----------|-------|
| `search_ops_manual` | READ | RAG over `data/knowledge/*.md` | — | HACCP, labour, suppliers, equipment; no platform call |
| `compare_store_performance` | READ | `GET /api/stores` + orders/analytics | commerce / intelligence | Fleet comparison |
| `run_inventory_reorder_tool` | READ→PROPOSE | Delegates to inventory agent | logistics | Same HITL as that agent |
| `run_dynamic_pricing_tool` | READ→PROPOSE | Delegates to pricing agent | commerce | Suggest only |
| `run_demand_forecast_tool` | READ→PROPOSE | Delegates to demand agent | intelligence | |
| `run_churn_prevention_tool` | READ→PROPOSE | Delegates to churn agent | core | |
| `run_shift_optimisation_tool` | READ→PROPOSE | Delegates to shift agent | core | |
| `run_kitchen_coach_tool` | READ→PROPOSE | Delegates to kitchen agent | core | |
| `run_review_response_tool` | READ→PROPOSE | Delegates to review agent | core | |
| `list_pending_proposals` | READ | Proposal store | — | Same data as `GET /agent/proposals` |
| `approve_proposal` | PROPOSE-RESOLVE | Proposal store | — | Manager approval; audited; not platform EXECUTE |
| `reject_proposal` | PROPOSE-RESOLVE | Proposal store | — | Manager rejection; audited |
| `transcribe_manager_audio` | READ | Gemini transcription | — | Composer microphone |
| `synthesize_manager_reply` | READ | Gemini TTS | — | Falls back to text if TTS is unavailable |

Topic and injection screening run **before** generation. Off-scope turns never reach Gemini.

---

## Agent 2 — Demand forecast

| Tool | Risk | Method + path | Platform | Notes |
|------|------|---------------|----------|-------|
| `list_stores` | READ | `GET /api/stores` | core | |
| `read_order_metrics` | READ | Orders / analytics | commerce / intelligence | Series for WMA |
| `compute_wma_forecast` | COMPUTE | In-process | — | Source of truth for forecast numbers |
| `write_forecast` | PROPOSE | `POST /api/analytics/forecast` | intelligence | Draft persist |
| `notify_managers` | PROPOSE | `GET /api/users` + `POST /api/notifications` | core | |

---

## Agent 3 — Inventory reorder

| Tool | Risk | Method + path | Platform | Notes |
|------|------|---------------|----------|-------|
| `list_stores` | READ | `GET /api/stores` | core | |
| `list_low_stock` | READ | `GET /api/inventory?storeId=&lowStock=true` | logistics | |
| `read_inventory_levels` | READ | `GET /api/inventory` | logistics | |
| `get_forecast_snippet` | READ | `GET /api/bi?type=demand-forecast` | intelligence | Guidance only |
| `create_draft_po` / `draft_purchase_order` | PROPOSE | `POST /api/purchase-orders` | logistics | Status **DRAFT** only; qty = reorder pack |
| `notify_managers` | PROPOSE | Notifications | core | |
| `execute_purchase_order` | EXECUTE | Blocked | logistics | Send to vendor — never |

---

## Agent 4 — Churn prevention

| Tool | Risk | Method + path | Platform | Notes |
|------|------|---------------|----------|-------|
| `list_stores` | READ | `GET /api/stores` | core | |
| `read_churn_segment` | READ | `GET /api/customers` + orders | core / commerce | Segment heuristics |
| `get_top_items` | READ | `GET /api/analytics?type=top-products` | intelligence | Offer ideas |
| `create_draft_campaign` / `draft_churn_campaign` | PROPOSE | `POST /api/campaigns` | core | Draft only |
| `notify_managers` | PROPOSE | Notifications | core | |
| `send_campaign_live` | EXECUTE | Blocked | core | Never auto-send |

---

## Agent 5 — Review response

| Tool | Risk | Method + path | Platform | Notes |
|------|------|---------------|----------|-------|
| `get_order_context` | READ | `GET /api/orders/{id}` | commerce | Event may supply `order_id` |
| `submit_review_draft_notification` / `draft_review_reply` | PROPOSE | Notifications | core | Draft + notify |
| `notify_managers` | PROPOSE | Notifications | core | |

---

## Agent 6 — Shift optimisation

| Tool | Risk | Method + path | Platform | Notes |
|------|------|---------------|----------|-------|
| `list_stores` | READ | `GET /api/stores` | core | |
| `read_staff_slots` | READ | `GET /api/users?storeId=` | core | Availability |
| `get_forecast_snippet` | READ | `GET /api/bi?type=demand-forecast` | intelligence | |
| `create_draft_shifts` / `draft_shift_roster` | PROPOSE | `POST /api/shifts/bulk` | core | Draft roster |
| `notify_managers` | PROPOSE | Notifications | core | |
| `confirm_shifts` | EXECUTE | Blocked | core | Manager publishes in the platform UI |

---

## Agent 7 — Kitchen coach

| Tool | Risk | Method + path | Platform | Notes |
|------|------|---------------|----------|-------|
| `list_stores` | READ | `GET /api/stores` | core | |
| `read_kitchen_metrics` | READ | `GET /api/orders/analytics?type=kitchen-metrics` | intelligence / commerce | Prep / volume |
| `draft_kitchen_brief` | PROPOSE | Proposal + notify | core | Brief only |
| `notify_managers` | PROPOSE | Notifications | core | |

---

## Agent 8 — Dynamic pricing

| Tool | Risk | Method + path | Platform | Notes |
|------|------|---------------|----------|-------|
| `list_stores` | READ | `GET /api/stores` | core | |
| `count_active_orders` | READ | `GET /api/orders?status=` | commerce | Overload signal |
| `count_recent_orders` | READ | `GET /api/orders?from=` | commerce | Underload / near close |
| `get_top_items` / `get_slow_items` | READ | Analytics / menu | intelligence / commerce | |
| `read_order_metrics` | READ | Orders / analytics | commerce / intelligence | |
| `compute_pricing_signal` | COMPUTE | In-process | — | Cap % from signal, not from the model |
| `propose_price_suggestion` / `suggest_price_adjustment` | PROPOSE | Notifications only | core | **Never** `PATCH /api/menu` |
| `patch_menu_price` | EXECUTE | `PATCH /api/menu/{id}` | commerce | Blocked — manager UI only |

---

## Shared blocked EXECUTE tools

| Tool | Intended final action | Why blocked |
|------|----------------------|-------------|
| `patch_menu_price` | Live price change | HITL; pricing suggests only |
| `execute_purchase_order` | Send PO to supplier | Manager approval |
| `execute_refund` | Capture refund | Manager / payment flow |
| `cancel_order_immediate` | Hard cancel | Customer path is cancel-request |
| `send_campaign_live` | Broadcast campaign | Draft only |
| `confirm_shifts` | Publish roster | Manager UI |

---

## Known limits

| Item | Status |
|------|--------|
| OpenAPI snapshot in CI | Not yet; fixtures align to platform enums |
| Delivery driver tracking | Out of scope |
| Place order from chat | Out of scope |
| All HTTP only via tools | Partial — model path uses tools; rule fallbacks may still call `httpx` |
| Platform ActionProposal API | This service stores proposals and exposes `GET`/`POST /agent/proposals*`; the platform remains the system of record for final execute after manager approval |
