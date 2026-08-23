# Paris fleet scale — synthetic world for the operator

Status: **locked** (2026-08-22). Inherits [hackathon-constraints.md](./2026-08-22-hackathon-constraints.md).
Phase: 5 (seed) + 6 (console must show the fleet, not one shop).

## Persona

You are the **owner-operator of MaSoVa pizza stores across Paris** (intra-muros plus a few inner-ring sites). The fleet is the product. One Oberkampf shop is only the **hero store** for the 4-minute close-up.

We seed a **Paris operator: 24 stores** — city + inner ring — large enough that policies, audits, and “which store is on fire” are real, small enough that SQLite and $150 of Gemini stay honest. We do not seed every restaurant in Île-de-France or all of France.

## Per-store size (not 24 copies of one shop)

Each store has a **profile**. Seed from the profile; do not clone DOM011 and rename the code.

MaSoVa `Store.code` is `DOM` + 3 digits (`DOM011`), not a city prefix. Geography lives on `name`, `address`, `countryCode=FR`, `currency=EUR`, `locale=fr-FR`. The console label is the neighbourhood; the database `code` is `DOM011`.

| Band | How many | Orders / day | Staff | Inventory posture | Typical sites |
|---|---|---|---|---|---|
| **Large** | 6 | 200–240 | 26–30 | higher `minimumStock`, more riders | Oberkampf (flagship), Belleville, BNF, République-adjacent |
| **Medium** | 12 | 120–160 | 16–20 | normal mins | most arrondissements + inner ring |
| **Small** | 6 | 70–90 | 10–14 | smaller mins, fewer perishable SKUs on hand | quieter west / inner-ring |

Calendar tags **multiply** that baseline (weekend_peak ×1.4, holiday_quiet ×0.45, rain ×1.25 delivery, event only on listed nearby stores). A small store on a dry Tuesday and a large store on a rainy Saturday must not look alike.

Flagship for the video: **DOM011** / human name “11e Oberkampf”, `store_id` `68a1f2c9e4b0a1234567890a`. Other stores: own ObjectIds, codes `DOM002`–`DOM020` plus inner-ring `DOM021`–`DOM024`.

## Locked volumes (14-day window — sums of the bands, not 24×150)

| Entity | Count | Why this size |
|---|---|---|
| Stores | **24** | Paris operator |
| SKUs / store | **48** catalogue; on-hand qty **varies by band** | same menu, different stock |
| Inventory rows | 24 × 48 = **1,152** | per store, per SKU — `currentStock` / `minimumStock` from the band |
| Orders (14 days) | **~45,000–55,000** | large/medium/small mixed, then calendar multipliers |
| Order lines | **~2.8 × orders** | MaSoVa order `items[]` |
| Customers | **~40,000** | `loyaltyInfo` + `orderStats` + `marketingOptIn` (GDPR default false) |
| Staff | **~480** | from the band, not 20 each |
| Shift slots (14 days) | **~6,000–7,000** | fewer slots on small / holiday_quiet |
| Reviews (14 days) | **~1,000–1,400** | more at large stores |
| Calendar days | **90** | tagged; 14 days have full orders |

Tests: `SELECT store_id, COUNT(*) FROM orders GROUP BY store_id` must show **at least 3 distinct daily-volume clusters**, not 24 stores within 10% of each other. Low-stock mozzarella **only** on DOM011 (hero); other stores may be healthy or short on different SKUs.

## What “big systems” means here (not decoration)

| System | How it shows up at 24-store scale |
|---|---|
| **Policies** | Same HITL everywhere. Pricing still cannot PATCH menu. Churn still drops no-consent customers. A key scoped to DOM011 cannot trigger DOM015. |
| **Humans** | One regional manager (Dana) sees a **fleet queue** (pending across 24 stores, not 3 cards from one shop). Approve is still per proposal. |
| **Audits** | Every run hash-chained. `GET /agent/runs?storeId=` filters. Tamper one line → `chain_verified: false`. |
| **Traffic** | Order volume varies by calendar tag (below). Agents read `count_active_orders` / `count_recent_orders` **per store**. Fleet rollup is a SUM, not a fake headline. |
| **Busy / dry / event / holiday / rain** | `calendar` table + Open-Meteo. Agents **skip LLM** when the signal is off (already true for pricing/inventory). That is how we evaluate: same code, different day type, different proposals. |

## Calendar tags (how the system is evaluated)

Each of 90 days has `tags` (JSON array). Seed 14 days of orders so the tags are visible in counts:

| Tag | Example | What agents should do |
|---|---|---|
| `weekday_dip` | Tue–Wed 17:00–19:00 | Pricing may propose a capped slot discount (hero scenario) |
| `weekend_peak` | Fri–Sat dinner | Inventory + shifts feel load; pricing does **not** panic-hike without a signal |
| `rain` | Open-Meteo precip ≥ 80% | Pricing may propose delivery-fee bump; demand up, riders down |
| `heatwave` | ≥ 32°C | Cold-drink forecast up (demand agent); no staff scoring |
| `holiday_quiet` | 15 août | Dry: underload, skip price-up, trim perishable reorder |
| `holiday_peak` | 14 juillet evening | Event-like surge |
| `event` | Stade de France match, Nuit Blanche | Nearby stores only (not all 24) |
| `dry` | Mid-week lunch, August weekday | Forecast down; kitchen coach still runs; no fake “AI insight” |

Tests (Phase 5/eval): at least one tagged day per row above produces the **expected class** of proposal or skip — using `OPS_PREFER_LLM=false` so CI and Cloud Run idle do not burn Gemini.

## $150 compute — hard rules

SQLite of this size is free (tens of MB, milliseconds). **Gemini is the scarce resource.**

1. Cloud Run: `min-instances=0`, `max-instances=1`, CPU only when a request or a job runs.
2. **Live LLM path is scoped:** `DEMO_FOCUS_STORE_ID` defaults to the DOM011 ObjectId. Scheduler jobs in DEMO_MODE iterate 24 stores on the **rule fallback** (`prefer_llm=false`) and only call Gemini for the focus store **or** stores with a live signal (low stock, overload, 1★ review).
3. Do **not** run 24 stores × 8 agents × Gemini every 30 minutes. That would empty $150 in a day.
4. Video: 2–4 Gemini runs (inventory DOM011, pricing DOM011, maybe churn, one blocked chat). Everything else on camera is SQL + traces already written.
5. After the video: scale to zero. Judging FAQ allows this if the video showed Cloud Run.
6. Open-Meteo is free. Do not add paid weather or maps APIs.

## Console must look like a fleet owner

Not a single-shop app with “24” in a subtitle only:

- Store picker lists **24 sites** (DOM011 selected).
- Top stats are **fleet**: stores, pending proposals across stores, auto-handled today, guard blocks.
- Needs-your-OK cards show **which store** (Oberkampf vs Batignolles vs BNF).
- Store proof defaults to DOM011 but can switch; inventory numbers stay the closed-loop hero.
- Live run stays the DOM011 inventory pass (close-up). A small line under it: “23 other stores ran on rules this cycle — 2 also waiting for OK.”

## Out of scope

- Simulating 95 IDF stores or 446 France stores
- Real-time rider GPS, call-centre, or franchise royalty ledgers
- Multi-region Cloud Run / autoscaling theatre
- Generating 50k orders with Gemini (seed is deterministic Python)
