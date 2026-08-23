# Demo Data Layer — Design Spec

Status: **revised 2026-08-22** (review pass). Phase 5 of 7.
Track: All Things Agentic Hackathon — The Fortified Enterprise Fleet
Pillar: 2 — "What is it allowed to do?" (proof-of-execution substrate)
Inherits: [hackathon-constraints.md](./2026-08-22-hackathon-constraints.md) — **read that file first**. This spec implements its data-provenance section.

## Problem

Every tool that reads/writes platform state goes over HTTP to `BACKEND_URL`
(`tools/ops_http.py`, `tools/backend_tools.py`) — the MaSoVa platform at
`192.168.50.88:8080`. That backend **will not be hosted on Google Cloud**.
It is unreachable from Cloud Run, and `backend_tools.py` still has field
drift against current `shared-models`.

Judges still need to see **where agent numbers come from**, and the
judging bar wants "proof of live execution — database updates or UI
changes." A canned dict is not a database. A live Dell IP is not a demo.

## Constraint

The demo backend is a real SQLite file. Tools actually SELECT/INSERT it.
Seed once, mutate during the demo. Same tool functions, same runtime,
same HITL: agents propose; only a manager approve applies a draft.

## Store identity (locked)

**Fleet:** 24 Paris-operator stores. Volumes, calendar tags, and Gemini
caps: [paris-fleet-scale.md](./2026-08-22-paris-fleet-scale.md).

**Flagship (video + golden-path tests):**

| Field | Value | MaSoVa |
|---|---|---|
| `stores.id` | `68a1f2c9e4b0a1234567890a` | Mongo `@Id` |
| `stores.code` | `DOM011` | `^DOM\\d{3}$` on `Store.code` |
| `name` | MaSoVa Paris 11e Oberkampf | `Store.name` |
| `countryCode` | `FR` | EU store, not India-null |
| `currency` | `EUR` | ISO 4217; prices integer minor units (cents, same idea as paise) |
| `locale` | `fr-FR` | BCP 47 |
| `status` | `ACTIVE` | `StoreStatus` |

**`DOM011` is never a `store_id`.** Console may show “11e Oberkampf”; SQL and agents use the ObjectId.

### MaSoVa likeness (shape vs content)

| Kind | Match? |
|---|---|
| **Shape** | Yes — `shared-models` / logistics / customer entities: `storeId`, `code`, `operatingHours` / `operatingConfig`, `basePrice` (minor units), `minimumStock` (not `reorderLevel`), nested `loyaltyInfo` + `orderStats`, `marketingOptIn` default **false**, order statuses `RECEIVED…CANCELLED` (no invented `APPROVED` refund). Adapter JSON is Spring `{content:[...]}` where the platform pages. |
| **Content** | Synthetic Paris pizza fleet, **not** a dump of the live Indian MaSoVa DB. Same kinds of things (stores, SKUs, POs, shifts, reviews), sized per store band. |
| **Per store** | Large / medium / small bands in paris-fleet-scale.md. Cloning one row 24 times is a spec fail. |

## Design

### Schema authority

Seed rows and HTTP-shaped JSON must match:

1. `docs/hackathon/EU_MARKET_SCENARIOS.md` (18 scenarios — preferred when
   the fixture file still has dual-tolerant legacy names)
2. `tests/fixtures/backend_contracts.py` canonical enums
   (`ORDER_STATUSES_CANONICAL`, `PO_STATUSES`, Spring `{content:[...]}`
   paging, nested `operatingConfig`, `basePrice` not `unitPrice`,
   `minimumStock` not `reorderLevel`, nested `loyaltyInfo` / `orderStats`)

While wiring the adapter, audit `backend_tools.py` / `ops_tools.py` and
correct remaining drift against those shapes. Do not invent a third schema.

### SQLite file

`data/demo/masova_demo.sqlite` (gitignored). Built by
`scripts/seed_demo_data.py`. Path override: `DEMO_DB_PATH`.

Tables (minimum): `stores`, `menu_items`, `orders`, `order_items`,
`customers`, `inventory`, `staff_shifts`, `purchase_orders`,
`purchase_order_items`, `campaigns`, `reviews`, `staff`, `calendar`.

`calendar(date, tags_json)` is required so busy/dry/rain/holiday/event
days are data, not comments in a rationale string.

Inventory columns follow the EU scenarios: `item_code`, `item_name`,
`current_stock` (REAL), `minimum_stock`, `unit`, `supplier_id`. Seed the
low-stock mozzarella / tomato-base rows from scenario 5 so the inventory
agent has something real to see.

### Adapter

`services/demo_backend.py` implements the same shapes as `ops_http.py`:
`get(path, params) -> dict`, `post(path, body) -> dict`, executing SQL.

`demo_mode()` reads `DEMO_MODE` **per call** (not import-cached).

Swap only at the HTTP helpers:

```python
# ops_http.get_json / post_json and backend_tools._get / _post
if demo_mode():
    return demo_backend.get(path, params)   # or .post
# else existing httpx
```

Tools above that layer do not change. `AgentRuntime` / `ops_llm.py` do not
change.

`DEMO_MODE=true` with a missing SQLite file **fails loudly**
("run scripts/seed_demo_data.py first") — never fall through to
`BACKEND_URL`.

### Writes vs HITL

| Call | DEMO_MODE SQL |
|---|---|
| GET inventory / orders / customers / reviews / metrics | SELECT |
| POST draft PO / draft campaign / draft shifts | INSERT status=`DRAFT` |
| price suggest | **no** `menu_items.price` UPDATE; proposal only (pricing agent never patches menu) |
| `POST /agent/proposals/{id}/resolve` APPROVED | apply payload: DRAFT → platform-next status (`PENDING_APPROVAL` or `APPROVED` per `PO_STATUSES` / campaign / shift enums). Set `approvedBy="demo-manager"` analogue if the table has the column. |
| resolve REJECTED | cancel draft or write `rejectionReason`; no advance |

Apply-on-approve is **manager-triggered**. It does not run when an agent
creates the proposal. On `DEMO_MODE=false`, resolve stays audit-only
(current `proposal_store` behaviour).

Implement apply in `runtime/proposal_apply.py` called from
`resolve_action_proposal` when `demo_mode()` is true. Unknown proposal
types log and skip apply rather than 500.

### On-camera SQL (DEMO_MODE only)

Judges will not SSH into Cloud Run. Add:

```
GET /agent/demo/tables/{table}
  require_scope("read:registry")
  DEMO_MODE=true only; 404 otherwise
```

`table` is an allowlist: `inventory`, `purchase_orders`, `menu_items`,
`customers`, `orders`, `reviews`. Returns `{table, store_code, rows: [...]}`
from a fixed SELECT (no client-supplied SQL). This is the before/after
shot in the video next to the console.

### Error handling

Demo SQL failure → same error translation tools already use for HTTP
failures. Callers must not need to know which backend answered.

## Testing (`tests/test_demo_backend.py`)

1. Seed creates **24** stores; flagship id `68a1f2c9e4b0a1234567890a`
   with `code=DOM011`, `countryCode=FR`, `currency=EUR`, `locale=fr-FR`.
   Order counts by `store_id` form at least 3 volume clusters (large /
   medium / small).
1b. `calendar` has 90 days and at least one of each tag in
    paris-fleet-scale.md (`rain`, `holiday_quiet`, `event`, …).
1c. Order count over 14 days is ≥ 20,000 (fleet), not a handful of
    demo rows. Golden-path inventory still uses DOM011 mozzarella 6.2/10.
2. Menu prices are integer cents; inventory has at least one
   `current_stock < minimum_stock` row for that store id.
3. Order statuses ⊆ `ORDER_STATUSES_CANONICAL`.
4. `demo_backend.get/post` round-trip Spring `{content:[...]}` shapes.
5. `DEMO_MODE=true` missing file raises a clear error; does not call httpx.
6. **Golden path (must be ≥1, never `>= 0`):**
   `OPS_PREFER_LLM=false`, `DEMO_MODE=true`, `run_inventory_reorder()`
   inserts at least one `purchase_orders` row with `status=DRAFT` for
   store `68a1f2c9e4b0a1234567890a`.
7. Resolving that proposal `APPROVED` advances the PO status. Rejecting
   does not.
8. Existing contract tests can take a `DEMO_MODE=true` parametrization
   where cheap; do not require live LLM.

## Out of scope

- Hosting or calling the real MaSoVa microservices from Cloud Run
- Seeding extra cities beyond Paris 11e
- Agent-side EXECUTE of prices / refunds / live campaigns
