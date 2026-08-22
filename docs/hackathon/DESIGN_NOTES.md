# Design notes — hackathon artifacts

Two standalone HTML pages, each self-contained (inline CSS, no external font/asset requests — same constraint as Claude Artifacts: no CDN dependencies, both light/dark themes defined via CSS custom properties). Open either file directly in a browser to view.

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

**Content is real, not placeholder:** proposal fields match `runtime/models.py`'s actual `ActionProposal` shape (`type`, `store_id`, `summary`, `rationale`, `risk` tier, `idempotency_key`), and the example data reflects the EU-market (Lisbon/DOM014, EUR pricing) grounding used throughout this submission — see `EU_MARKET_SCENARIOS.md` in this folder for the full 18-scenario set these examples are drawn from.

## Provenance

Both pages were drafted as Claude Artifacts during planning conversations for this submission, then extracted here as static files for version control. If either needs visual updates, edit the file directly — these copies are now the source of truth, not the original Artifact URLs.
