# Capability map — tools ↔ platform APIs

Maps every customer-chat and ops tool this service exposes to risk tier, HTTP
surface, and platform service. Source of truth for “in scope” integrations.

**Auth**

| Caller | Credential |
|--------|------------|
| Customer chat tools (`backend_tools`) | Customer JWT (`Authorization: Bearer`) |
| Ops tools (`ops_tools` / `ops_http`) | `AGENT_TOKEN` |
| Manual agent triggers | `AGENT_TRIGGER_API_KEY` |

**HTTP exit points (preferred)**

| Module | Role |
|--------|------|
| `tools/backend_tools.py` | Customer chat → platform |
| `tools/ops_http.py` + `tools/ops_tools.py` | Ops LLM tool loop → platform |

Rule-based agent fallbacks still call `BACKEND_URL` with `httpx` inside some
`agents/*_agent.py` files (same paths as tools). Prefer tools for new work;
dedupe is incremental.

**Risk tiers** (see `runtime/policy.py`)

| Tier | Meaning |
|------|---------|
| READ | Fetch data only |
| COMPUTE | Local math / signal from tool inputs |
| PROPOSE | Draft + notify; `requires_approval=true`; no silent execute |
| EXECUTE | **Blocked** — never allowlisted |

Platform services: **core** · **commerce** · **payment** · **logistics** · **intelligence**

---

## Agent 1 — Support chat (ADK)

Top intents (current tools only — no full checkout):

| Intent | Tools | Notes |
|--------|-------|-------|
| Order status | `get_order_status` | JWT ownership enforced by backend |
| Menu browse | `get_menu_items` | Filter cuisine/category client-side |
| Store hours / open | `get_store_hours` | Nested `operatingConfig` or flat times |
| Loyalty | `get_loyalty_points` | Identity from JWT only |
| Wait time | `get_store_wait_time` | Heuristic from active orders if no ETA field |
| Complaint | `submit_complaint` | Pending manager handling |
| Cancel | `cancel_order` | Cancel **request**; manager approval copy |
| Refund | `request_refund` | Refund **request**; manager approval copy |

| Tool | Risk | Method + path | Platform service | Notes |
|------|------|---------------|------------------|-------|
| `get_order_status` | READ | `GET /api/orders/{id}` | commerce | Status enum from shared-models (see fixtures) |
| `get_menu_items` | READ | `GET /api/menu?storeId=&available=` | commerce / core | Page or list shape |
| `get_store_hours` | READ | `GET /api/stores/{id}` | core | Nested vs flat hours |
| `get_loyalty_points` | READ | `GET /api/customers/{id}` | core / commerce | **Never** use LLM `customer_id` |
| `get_store_wait_time` | READ | `GET /api/orders?storeId=&status=` | commerce | Active-order count heuristic |
| `submit_complaint` | PROPOSE | `POST /api/complaints` (or notifications fallback) | core | Draft / ticket |
| `cancel_order` | PROPOSE | `POST /api/orders/{id}/cancel-request` | commerce | Not instant cancel |
| `request_refund` | PROPOSE | `POST /api/refunds` (request) | payment | Pending approval |

**Out of scope / FUTURE (chat)**

| Capability | Status |
|------------|--------|
| Place order / checkout | OUT OF SCOPE |
| Live delivery tracking map | FUTURE (logistics) |
| Payment capture / card update | OUT OF SCOPE |
| Instant cancel / execute refund | NEVER (EXECUTE) |

---

## Agent 2 — Demand forecast

| Tool | Risk | Method + path | Platform service | Notes |
|------|------|---------------|------------------|-------|
| `list_stores` | READ | `GET /api/stores` | core | |
| `read_order_metrics` | READ | (aggregates orders / analytics) | commerce / intelligence | Series for WMA |
| `compute_wma_forecast` | COMPUTE | *(local)* | — | **Source of truth for numbers** |
| `write_forecast` | PROPOSE | `POST /api/analytics/forecast` | intelligence | Persist draft forecast |
| `notify_managers` | PROPOSE | `GET /api/users` + `POST /api/notifications` | core | |

---

## Agent 3 — Inventory reorder

| Tool | Risk | Method + path | Platform service | Notes |
|------|------|---------------|------------------|-------|
| `list_stores` | READ | `GET /api/stores` | core | |
| `list_low_stock` | READ | `GET /api/inventory?storeId=&lowStock=true` | logistics | |
| `read_inventory_levels` | READ | `GET /api/inventory` | logistics | Alias path of list/read |
| `get_forecast_snippet` | READ | `GET /api/analytics/forecast` | intelligence | Qty guidance only from tools |
| `create_draft_po` / `draft_purchase_order` | PROPOSE | `POST /api/purchase-orders/auto-generate` | logistics | Status **DRAFT** only |
| `notify_managers` / `notify_manager` | PROPOSE | notifications | core | |
| `execute_purchase_order` | EXECUTE | *(blocked)* | logistics | Final PO send — never |

---

## Agent 4 — Churn prevention

| Tool | Risk | Method + path | Platform service | Notes |
|------|------|---------------|------------------|-------|
| `list_stores` | READ | `GET /api/stores` | core | |
| `read_churn_segment` | READ | `GET /api/customers` + orders | core / commerce | Segment heuristics |
| `get_top_items` | READ | `GET /api/analytics/products` | intelligence | Offer suggestions |
| `create_draft_campaign` / `draft_churn_campaign` | PROPOSE | `POST /api/campaigns` | core | Draft campaign only |
| `notify_managers` | PROPOSE | notifications | core | |
| `send_campaign_live` | EXECUTE | *(blocked)* | core | Never auto-send |

---

## Agent 5 — Review response

| Tool | Risk | Method + path | Platform service | Notes |
|------|------|---------------|------------------|-------|
| `get_order_context` | READ | `GET /api/orders/{id}` | commerce | RabbitMQ event may supply order_id |
| `submit_review_draft_notification` / `draft_review_reply` | PROPOSE | notifications | core | Draft text + notify |
| `notify_managers` | PROPOSE | notifications | core | |

---

## Agent 6 — Shift optimisation

| Tool | Risk | Method + path | Platform service | Notes |
|------|------|---------------|------------------|-------|
| `list_stores` | READ | `GET /api/stores` | core | |
| `read_staff_slots` | READ | `GET /api/users?storeId=` | core | Staff availability |
| `get_forecast_snippet` | READ | `GET /api/analytics/forecast` | intelligence | |
| `create_draft_shifts` / `draft_shift_roster` | PROPOSE | `POST /api/shifts/bulk` | core | Draft roster |
| `notify_managers` | PROPOSE | notifications | core | |
| `confirm_shifts` | EXECUTE | *(blocked)* | core | Manager confirms in UI |

---

## Agent 7 — Kitchen coach

| Tool | Risk | Method + path | Platform service | Notes |
|------|------|---------------|------------------|-------|
| `list_stores` | READ | `GET /api/stores` | core | |
| `read_kitchen_metrics` | READ | `GET /api/analytics/orders` | intelligence / commerce | Prep / volume |
| `draft_kitchen_brief` | PROPOSE | *(proposal + notify)* | core | Coaching brief only |
| `notify_managers` | PROPOSE | notifications | core | |

---

## Agent 8 — Dynamic pricing

| Tool | Risk | Method + path | Platform service | Notes |
|------|------|---------------|------------------|-------|
| `list_stores` | READ | `GET /api/stores` | core | |
| `count_active_orders` | READ | `GET /api/orders?status=` | commerce | Overload signal |
| `count_recent_orders` | READ | `GET /api/orders?from=` | commerce | Underload / near-close |
| `get_top_items` / `get_slow_items` | READ | analytics products / menu | intelligence / commerce | |
| `read_order_metrics` | READ | orders / analytics | commerce / intelligence | |
| `compute_pricing_signal` | COMPUTE | *(local)* | — | Cap % from signal, not LLM |
| `propose_price_suggestion` / `suggest_price_adjustment` | PROPOSE | notifications only | core | **Never** `PATCH /api/menu` |
| `patch_menu_price` | EXECUTE | `PATCH /api/menu/{id}` | commerce | **Blocked** — manager UI only |

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

## Gaps (honest)

| Gap | Status |
|-----|--------|
| OpenAPI snapshot checked into CI | FUTURE — fixtures + Java enum alignment for now |
| Delivery driver tracking tools | OUT OF SCOPE |
| Place order from chat | OUT OF SCOPE |
| Unified HTTP only via tools (no agent fallback httpx) | PARTIAL — LLM path uses tools; rule fallbacks still inline |
| Platform ActionProposal storage API | Local `proposal_store` + `GET/POST /agent/proposals*` (this service); platform UI remains final execute |
