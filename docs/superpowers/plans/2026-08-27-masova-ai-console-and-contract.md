# MaSoVa AI — Contract Alignment + Grok Console Implementation Plan

> Implementation checklist. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a hackathon-winning **MaSoVa AI** chat console (Grok-like, zero hardcoded ops numbers) on DEMO_MODE, with MaSoVa-correct tools/HITL and industry-aligned tool provenance.

**Architecture:** Keep Google ADK + typed tools → DEMO SQLite (MaSoVa-shaped SoR stand-in). Replace `fleet-console-mockup.html` with a chat-first **MaSoVa AI** UI wired only to live FastAPI endpoints. Fix reject-apply, unify ops HTTP, align paths/fields to MaSoVa, add `evidence[]` on proposals.

**Tech Stack:** Python 3.9+, FastAPI, Google ADK, SQLite demo_backend, vanilla HTML/CSS/JS console (no CDN), pytest.

**Spec:** `docs/superpowers/specs/2026-08-27-masova-contract-alignment-design.md`  
**Also inherits:** `docs/superpowers/specs/2026-08-22-hackathon-constraints.md`

## Global Constraints

- Product UI name: **MaSoVa AI**
- Submission runtime: `DEMO_MODE=true`; smoke against demo SQLite only
- No hardcoded operational numbers in UI or agents (seed script only)
- Agents propose; manager Approve applies in DEMO; EXECUTE stays blocked
- Public story: Gemini + Google ADK (never name alternate LLM providers in docs/UI/commits)
- Deadline priority: unbroken demo golden path > live MaSoVa JWT/execute

## File map

| File | Role |
|------|------|
| `src/masova_agent/runtime/proposal_apply.py` | Restore reject apply for DEMO |
| `src/masova_agent/main.py` | Serve new console; resolve imports |
| `docs/hackathon/masova-ai-console.html` | New Grok-like MaSoVa AI UI (replace mockup as `/console` target) |
| `src/masova_agent/tools/ops_http.py` | Shared ops HTTP (already) |
| `src/masova_agent/tools/ops_tools.py` | Path/field + evidence alignment |
| `src/masova_agent/tools/backend_tools.py` | Chat field/path MaSoVa match |
| `src/masova_agent/services/demo_backend.py` | MaSoVa path aliases + shapes |
| `src/masova_agent/agents/*.py` | Route rule paths through `ops_http` |
| `src/masova_agent/runtime/models.py` / proposal save | `evidence[]` on proposals |
| `tests/fixtures/backend_contracts.py` | MaSoVa-correct fixtures |
| `docs/CAPABILITY_MAP.md` | Match code paths |
| `tests/test_console_masova_ai.py` | No-hardcode + chip wiring smoke |
| `tests/test_demo_volume.py` | Paris fleet volume gates |

---

### Task 1: Unbreak proposal reject (P0)

**Files:**
- Modify: `src/masova_agent/runtime/proposal_apply.py`
- Modify: `src/masova_agent/main.py` (only if import path changes)
- Test: `tests/test_proposals.py`

**Interfaces:**
- Produces: `apply_rejected_proposal(proposal: dict, note: str = "") -> bool` (DEMO only; cancels draft PO/campaign/shifts)

- [ ] **Step 1: Write failing test for reject apply**

```python
# tests/test_proposal_reject_apply.py
def test_apply_rejected_proposal_importable_and_cancels_draft_po(tmp_path, monkeypatch):
    from masova_agent.runtime import proposal_apply
    assert hasattr(proposal_apply, "apply_rejected_proposal")
```

- [ ] **Step 2: Run test — expect FAIL (function missing)**

Run: `pytest tests/test_proposal_reject_apply.py -v`

- [ ] **Step 3: Restore `apply_rejected_proposal` in `proposal_apply.py`**

Re-add the deleted DEMO implementation (CANCELLED + rejection_reason for PO/campaign/shifts; price suggestion no-op). Keep `apply_approved_proposal` unchanged.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_proposal_reject_apply.py tests/test_proposals.py -v`  
Expected: PASS (including REJECTED resolve 200)

- [ ] **Step 5: Commit**

```bash
git add src/masova_agent/runtime/proposal_apply.py tests/test_proposal_reject_apply.py
git commit -m "$(cat <<'EOF'
fix(proposals): restore demo reject apply for HITL decline

EOF
)"
```

---

### Task 2: MaSoVa AI console shell (Grok-like HTML)

**Files:**
- Create: `docs/hackathon/masova-ai-console.html`
- Modify: `src/masova_agent/main.py` — `/console` serves the new file
- Test: `tests/test_console.py` (update path assertions)

**Interfaces:**
- Consumes: `GET /agents`, `GET /agent/proposals`, `POST /agent/proposals/{id}/resolve`, `POST /agents/{name}/trigger`, `GET /agent/runs/{id}`, `GET /agent/demo/tables/{table}`
- Injected demo API key pattern already in `main.py` for console fetches

- [ ] **Step 1: Failing test — console HTML contains brand and no canned mozz string**

```python
def test_console_is_masova_ai_and_has_no_canned_inventory_copy():
    from pathlib import Path
    html = (Path("docs/hackathon/masova-ai-console.html")).read_text()
    assert "MaSoVa AI" in html
    assert "6.2 / 10" not in html
    assert "mozz 6.2" not in html.lower()
```

- [ ] **Step 2: Run — FAIL (file missing)**

- [ ] **Step 3: Implement `masova-ai-console.html`**

Self-contained HTML/CSS/JS (no CDN). Dark Grok-like layout:

- Brand: **MaSoVa AI**
- Left rail: **all 8 agents** from `GET /agents` + status from proposals / runs (chat + 7 ops). Chips are shortcuts only — they do not replace the full fleet rail.
- Main: chat thread
- Chips: **Run inventory**, **Pricing signal**, **Store proof**
- Composer
- Inline proposal cards with Approve/Decline
- On API failure: show error text — **never** invent stock numbers
- Use same API-key injection approach as current console (`main.py` console endpoint)

Wire chips:

```javascript
// Pseudocode — implement fully in the HTML file
async function runInventory() {
  appendUser("Run inventory for focus store");
  const run = await post(`/agents/inventory_reorder/trigger`, {});
  await pollRun(run.run_id); // append tool step chips from run.steps / stations
  await refreshProposalsIntoThread(); // inline Needs your OK cards
}
async function storeProof() {
  const inv = await get(`/agent/demo/tables/inventory?storeId=...`);
  const pos = await get(`/agent/demo/tables/purchase_orders?storeId=...`);
  appendProofCard(inv, pos); // render rows from JSON only
}
```

Focus store id: from env/bootstrap endpoint or existing demo focus constant exposed by API — do not hardcode kg/L.

- [ ] **Step 4: Point `/console` at new file**

In `main.py`, set `console_path` to `docs/hackathon/masova-ai-console.html`.

- [ ] **Step 5: Run tests**

`pytest tests/test_console.py tests/test_console_masova_ai.py -v` (create/adapt as needed)

- [ ] **Step 6: Commit**

```bash
git add docs/hackathon/masova-ai-console.html src/masova_agent/main.py tests/
git commit -m "$(cat <<'EOF'
feat(console): MaSoVa AI Grok-like chat UI wired to live APIs

EOF
)"
```

---

### Task 3: Chip → API integration tests (demo)

**Files:**
- Create: `tests/test_masova_ai_chips.py`
- Modify: console JS if tests reveal gaps

- [ ] **Step 1: Write integration-style tests with TestClient + DEMO_MODE**

```python
def test_inventory_trigger_creates_run_and_proposal(client, demo_env):
    # auth headers with scoped key
    r = client.post("/agents/inventory_reorder/trigger", headers=headers)
    assert r.status_code == 200
    # list proposals — any DRAFT_PURCHASE_ORDER must have payload quantities
    # that appear in demo inventory low-stock for focus store
```

- [ ] **Step 2: Run — may FAIL until DEMO seed has low stock on focus store**

- [ ] **Step 3: Fix seed or agent only if needed (no UI hardcode)**

- [ ] **Step 4: Commit**

```bash
git commit -m "$(cat <<'EOF'
test(console): assert inventory chip path grounds proposals in SQL

EOF
)"
```

---

### Task 4: Demo volume CI gates

**Files:**
- Create: `tests/test_demo_volume.py`

**Note:** Current DB already ~24 stores / 50k orders / 1152 inventory — lock that in CI when `data/demo/masova_demo.sqlite` is present (skip if absent in bare CI — or use seed script in fixture).

- [ ] **Step 1: Write volume tests**

```python
@pytest.mark.skipif(not Path("data/demo/masova_demo.sqlite").exists(), reason="no demo db")
def test_paris_fleet_volume_bands():
    # stores == 24
    # orders >= 45000
    # inventory == 1152
    # at least 3 distinct order-count clusters by store
```

- [ ] **Step 2: Run — expect PASS on developer machine with seeded DB**

- [ ] **Step 3: Commit**

---

### Task 5: Align analytics / BI / PO draft paths

**Files:**
- Modify: `src/masova_agent/tools/ops_tools.py`
- Modify: `src/masova_agent/services/demo_backend.py` (route aliases)
- Modify: `docs/CAPABILITY_MAP.md`
- Modify: `tests/fixtures/backend_contracts.py`
- Test: `tests/test_ops_llm_tools.py`, `tests/test_demo_backend.py`

**Interfaces:**
- `get_forecast_snippet` → `GET /api/bi?type=demand-forecast` (demo_backend accepts alias)
- `get_top_items` → `GET /api/analytics?type=top-products`
- `read_kitchen_metrics` → `GET /api/orders/analytics?type=...` (or documented MaSoVa equivalent)
- Draft PO → `POST /api/purchase-orders` with `status=DRAFT` (not fake body to auto-generate)

- [ ] **Step 1: Failing tests for new paths in demo_backend routing**

- [ ] **Step 2: Implement demo_backend routes + ops_tools callers**

- [ ] **Step 3: Update CAPABILITY_MAP to match code**

- [ ] **Step 4: pytest targeted suite — PASS**

- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
fix(ops): align tool paths with MaSoVa BI/analytics and DRAFT POs

EOF
)"
```

---

### Task 6: Field alignment (loyalty, supplier, order item price)

**Files:**
- Modify: `backend_tools.py`, `ops_tools.py`, `demo_backend.py`, fixtures
- Test: `tests/test_backend_tools.py`, `tests/test_backend_contracts.py`

- [ ] Prefer `loyaltyInfo.totalPoints`, `primarySupplierId`, `OrderItem.price`, `itemName`/`minimumStock`
- [ ] Remove inventing `OrderStatus.PENDING` / refund `APPROVED`
- [ ] Tests + commit: `fix(contracts): MaSoVa field names in tools and fixtures`

---

### Task 7: Unifyмент — unify rule agents onto `ops_http`

**Files:**
- Modify: `agents/demand_forecasting_agent.py`, `churn_prevention_agent.py`, `shift_optimisation_agent.py`, `kitchen_coach_agent.py`, `dynamic_pricing_agent.py`, `review_response_agent.py`
- Keep: `inventory_reorder_agent.py` as reference pattern

- [ ] Replace raw `httpx` + `backend_url` with `get_json`/`post_json` from `ops_http`
- [ ] One shift bulk body shape; one forecast write shape
- [ ] Test: `pytest tests/test_agents.py -v` (mock ops_http)
- [ ] Commit: `refactor(agents): route rule fallbacks through ops_http`

---

### Task 8: Proposal `evidence[]` provenance

**Files:**
- Modify: `runtime/models.py` (if ActionProposal typed), `ops_tools.py` create_draft_* , `agent_runtime` save path
- Test: `tests/test_proposals.py`

**Produces:** each new proposal includes:

```python
"evidence": [
  {"tool": "list_low_stock", "row_id": "...", "field": "currentStock", "value": 6.2}
]
```

copied from tool results — never LLM-authored alone.

- [ ] Failing test asserting evidence present on DRAFT_PURCHASE_ORDER from inventory path
- [ ] Implement
- [ ] Console card renders evidence from proposal JSON
- [ ] Commit: `feat(proposals): attach tool evidence for grounded HITL cards`

---

### Task 9: Strip old console hardcoding / archive

**Files:**
- Modify or archive: `docs/hackathon/fleet-console-mockup.html` (add banner “superseded by masova-ai-console.html” or delete static kg/L strings)
- Grep repo for `6.2 / 10`, `mozz 6.2`, canned tomato lines — remove from camera paths

- [ ] `rg "6\\.2 / 10|mozz 6\\.2|18kg mozzarella" docs/hackathon src` → clean
- [ ] Commit: `chore(console): remove canned inventory demo strings`

---

### Task 10: Demo smoke checklist + verify

**Files:**
- Update: `docs/SMOKE_CHECKLIST.md` for MaSoVa AI chips

- [ ] Manual DEMO_MODE rehearsal:
  1. Open `/console` — brand MaSoVa AI
  2. Store proof chip — numbers from API
  3. Run inventory — tool steps in thread
  4. Approve — Store proof again shows PO status change
  5. Decline path does not 500
- [ ] `pytest tests/ -q` green
- [ ] Commit docs only if checklist changed

---

## Spec coverage check

| Spec section | Task(s) |
|--------------|---------|
| §9 HITL reject P0 | Task 1 |
| §19 MaSoVa AI Grok UI + chips | Tasks 2–3 |
| §16 volume | Task 4 |
| §6–7 paths/fields | Tasks 5–6 |
| §8 ops_http unify | Task 7 |
| §18 no hardcode / §20 evidence | Tasks 8–9 |
| §12–14 verify / win test | Task 10 |
| §21 ADK/Gemini stay | No framework swap (global) |
| Live JWT / execute | Out of plan (deferred) |

## Execution handoff

Plan saved to `docs/superpowers/plans/2026-08-27-masova-ai-console-and-contract.md`. Execute tasks in order with review checkpoints between tasks.
