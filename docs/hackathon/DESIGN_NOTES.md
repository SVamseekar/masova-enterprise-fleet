# Design notes — hackathon artifacts

Two standalone HTML pages, each self-contained (inline CSS, no external font/asset requests — no CDN dependencies; both light/dark themes defined via CSS custom properties). Open either file directly in a browser to view.

## `fleet-readiness-plan.html`

**Treatment:** utilitarian document — a build plan/roadmap the user references while executing, not a pitch page. Real typographic hierarchy and considered spacing, no flashy hero.

**Design plan followed:**
- **Color** — warm cream/parchment ground (`#f3f1ea`) with a copper/amber accent (`#a9682f`), evoking an audit-ledger, ops-document register. Dark mode swaps to deep slate (`#15141a`) with the accent brightened (`#d9a24b`) for contrast.
- **Type** — serif display/body pairing (Iowan Old Style / Palatino fallback stack, Charter for body) for a "dossier" feel, monospace (`SFMono-Regular`/Menlo stack) for labels, timestamps, and code references — deliberately not a tech-generic sans stack.
- **Layout** — single-column vertical spine down the left for the 7 build phases (a real sequence, order matters), each phase a card with status chip and KYA-pillar tag. Architecture diagram as inline SVG. Demo script as a time-coded table.

**Structural devices used because they encode real information, not decoration:**
- Phase numbering (01–07) — a genuine build sequence
- Status chips (`gap`/`build`/`done`) — real state of each phase as of the plan's last update
- Pillar tags (1/2/3) — map every phase back to the Know-Your-Agent framing

## `fleet-console-mockup.html`

**Treatment:** UI mockup — scanned and operated, not read top-to-bottom. Craft shifts to information design over typography.

**Design plan followed:**
- **Color** — dark-first charcoal-green ground (`#14181a`), suited to an ops console viewed in low light (kitchen/back-office context). One warm accent (`#e0964a`) reserved for "needs your attention" (pending proposals). Semantic color kept separate from the accent: green=approved, muted red=rejected/blocked, blue-grey=running/auto.
- **Type** — condensed technical sans for headers/labels, clean body sans for copy, monospace for agent IDs, timestamps, store codes, idempotency keys — the texture a real audit tool has.
- **Layout** — classic ops-console shell: left rail (agent registry + nav), top bar (store context, manager identity), main area split into the proposal queue (front and center — the thing needing action) and a secondary audit/chat panel.

**Content is real, not placeholder:** proposal fields match `runtime/models.py`'s actual `ActionProposal` shape (`type`, `store_id`, `summary`, `rationale`, `risk` tier, `idempotency_key`), and the example data reflects the EU-market (Paris/DOM011, EUR pricing) grounding used throughout this submission — see `EU_MARKET_SCENARIOS.md` in this folder for the full 18-scenario set these examples are drawn from.

## Provenance

Both pages were drafted during planning for this submission, then checked in as static files for version control. If either needs visual updates, edit the file directly — these copies are the source of truth.

## Revision: `fleet-console-mockup.html` rebuilt for store managers, not developers

**Problem:** the original console read like an internal ops/dev tool — monospace `proposal_id`/`idempotency_key` strings in the primary view, jargon like "PROPOSE tier", "hash-linked reasoning-chain", raw GDPR article citations, a "Clients on /agent/chat" nav section. The actual audience is a restaurant store manager with no technical background, deciding whether to tap Approve.

**What changed:**
- **Plain language everywhere in the primary view.** "ActionProposal" → "thing needing your OK"; agent names became human roles (Pricing Assistant, Inventory Watcher, Customer Care, Kitchen Coach…); rationale text rewritten as a manager would actually read it (the GDPR consent-exclusion note became "3 similar customers were left out because they haven't agreed to receive marketing messages").
- **Technical detail didn't disappear — it moved.** Each proposal card keeps a collapsed `<details>` "Technical details" disclosure with the real `proposal_id`, `idempotency_key`, risk tier, and consent-basis citation, so the rigor a hackathon judge wants to see is still there, just not competing with the primary decision.
- **Removed dev-only surface entirely:** the "Clients on /agent/chat" nav section and the version/runtime footer (`GET /agents · v0.9.0 · Redis · APScheduler`) added nothing for a manager and are gone; a single small "Built on Google ADK & Gemini" credit line remains for the technology-requirement visibility judging needs.
- **Interaction, not just visuals:** Approve/Decline buttons are now live (vanilla JS, no dependencies) — clicking removes the card with a short transition and updates the pending count, down to an "All caught up" empty state. Lets the mockup double as a click-through demo rather than a static screenshot.
- **Warmer palette, larger targets.** Shifted off the dark charcoal-green "ops console at night" treatment toward a warm cream/terracotta palette that reads as approachable rather than technical; all buttons ≥44px tall (touch-target minimum); base type size raised from 14px to 15.5px for readability.
- **Icons are inline SVG, not monospace codes or emoji** — one per assistant role, drawn on a consistent stroke grid, so the left rail scans by shape instead of by reading abbreviated agent slugs.

Kept unchanged: the self-contained/no-CDN constraint, light/dark theme via CSS custom properties, and the underlying numbers from `EU_MARKET_SCENARIOS.md` — market is Paris 11e (DOM011), not Lisbon. Console now has Live run (station canvas) and Store proof (before/after ledger) in addition to the queue.

## Revision 2: orchestration-awareness, without the clutter

Follow-up pass after design feedback confirmed the direction (warm material design, clay-inspired softness kept subtle, not full neumorphism/skeuomorphism) and asked for the UI to read as *orchestration-aware*:

- **Per-agent status chips** in the left rail — `Monitoring` / `Waiting for OK` / `Scheduled`, each a small dot + label, derived from actual state (an assistant with a live proposal in the queue shows "Waiting for OK"; this also fixed a data bug where Pricing Assistant was marked idle/"stub" despite having a pending proposal).
- **Per-agent tinted icon tiles** instead of one uniform beige badge — green for Inventory Watcher, blue for Sales Forecast and Chat Helper, amber for Pricing, rose for Customer Care, gold for Review Replies, teal for Shift Planner, clay/terracotta for Kitchen Coach. Agent identity carries color; proposal cards, history rows, and the chat panel stay flatter and more material — color is reserved for identity and semantic state (good/warn/live), never spent on data containers.
- **A "running now" strip** above the activity panel — one live example (`Inventory Watcher · checking supplier prices · 62% · Stop`) with a pulsing dot and thin progress bar (respects `prefers-reduced-motion`). Makes in-progress work visible without adding 3D/decorative styling.
- **Pricing Assistant's icon** swapped from a generic adjustment-dial glyph to an actual price tag, for one-glance recognition (the "reserve skeuomorphism for affordance, not decoration" principle — restaurant-native icons where they help identification, nothing textured or literal beyond that).

Approve/Decline buttons were already solid-fill (green) / bordered (red) with no recessed or neumorphic treatment — confirmed as correct, left unchanged.

## Revision 3: enterprise agent control-plane positioning

Follow-up pass reframing the mockup from "friendly assistant app" toward "credible enterprise agent fleet," per a detailed spec covering positioning, evidence structure, and demo flow. Scope stayed UI-only — this repo has no live frontend, so nothing here calls a real backend; every number/policy claim added was sourced from `EU_MARKET_SCENARIOS.md` or `AGENT_PLATFORM.md`, none invented. See the chat transcript for the full real-vs-demo breakdown given to the user.

- **Header identity**: brand renamed "Masova Agent Fleet" with a "Autonomous restaurant operations" subline; `<title>` updated to match (the artifact's tab/gallery name follows the `<title>` tag).
- **Decision cards carry real evidence**, not just a rationale sentence. Each of the 3 proposals now has a "Why this decision" disclosure with three grounded sections — What the agent saw / What it's proposing / Guardrails in place — built only from data already present in `EU_MARKET_SCENARIOS.md` (e.g. pricing: "-34% vs. 8-week average," "+19% at comparable stores," "confidence: high" — all direct quotes from the source rationale, not new numbers).
- **Customer Care's consent split promoted** from a sentence to a visible stat pair (12 eligible / 3 excluded — no marketing consent), matching the source scenario's real `excludedForConsent: 3` field.
- **Approve → "Approve & apply"**, and approving/declining now writes a live entry to the top of the activity feed ("✓ Applied by Pricing Assistant · 12:41 PM") — reinforces the audit-trail message, still entirely client-side/simulated (no backend write).
- **Security panel branded "Masova Agent Guard"** — copy change only. Flagging honestly: this depicts a capability the actual backend does **not** have yet — `fleet-readiness-plan.html` phase 04 ("Model Armor–lite") is listed as a gap, not built. The mockup shows target behavior, not a shipped feature.
- **Per-agent detail disclosure** added to every rail entry (native `<details>`, no JS) — Typically does / Guardrail, written from each agent's real documented behavior in `AGENT_PLATFORM.md` (e.g. Pricing Assistant: "can never edit the menu directly," sourced from "never calls PATCH /api/menu — only manager notifications with capped % suggestions").
- **Copy tweaks** reinforcing async/no-prompt-needed framing ("You don't have to ask your agents to work — they're already on it") and de-emphasizing chat ("Optional — your agents don't wait to be asked").
