# Ship: local LLM → Gemini 3.5 → Cloud Run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Note on task shape:** unlike the other 6 phases, this plan has no code
> to TDD — it is a deployment runbook. Each task ends with a concrete,
> independently verifiable deliverable (a passing local pass, a running
> container, a live Cloud Run URL) instead of a passing test, but the same
> "no placeholders, real content only" rule applies to every step.

**Goal:** After Phases 1–6 are green locally, swap `LLM_MODEL` to `gemini-3.5-flash` and deploy this service to Cloud Run with `DEMO_MODE=true` so the video shows a live `.run` URL, SQLite-backed agents, and no MaSoVa platform host.

**Architecture:** Env + container + Cloud Run. Dockerfile must COPY seed script + console HTML. SQLite is instance-local → `--max-instances=1`.

**Tech Stack:** Docker, Google Cloud SDK (`gcloud`), Cloud Run, Secret Manager.

**Spec:** `docs/superpowers/specs/2026-08-22-ship-deployment-runbook.md`

**Inherits:** `docs/superpowers/specs/2026-08-22-hackathon-constraints.md`.

## Global Constraints

- This plan only starts after Phases 1-6 are implemented and their test suites are green.
- **Do not deploy Cloud Run until the $150 GCP credit is on the billing account.** The request is already submitted; wait. Do not spend personal GCP money.
- Locked submission model: `LLM_MODEL=gemini-3.5-flash` (and `OPS_LLM_MODEL`). `gemini-2.5-flash` is a Stage 1 fail.
- Cloud Run is `DEMO_MODE=true`, `--max-instances=1`. This is the demo backend, not a second "prod" service.
- Secrets go through Secret Manager — never plaintext `--set-env-vars`.
- Tracked files, API errors, README, video: Gemini / Google ADK only. The local iteration provider is named only in gitignored `CLAUDE.md`. After this plan, that brand must not appear in any tracked file.
- Record the golden path against the live `.run.app/console` URL, with `GET /agent/demo/tables/inventory` as the before/after shot.

---

### Task 1: Full local pass (`DEMO_MODE=true`)

**Files:** none modified — verification only.

- [ ] **Step 1: Confirm `.env` is set for local iteration + demo data**

```bash
grep -E "^LLM_API_KEY|^LLM_MODEL|^DEMO_MODE" .env
```
Expected: `DEMO_MODE=true`, `LLM_API_KEY` non-empty, `LLM_MODEL` set (local iteration id is fine here). Seed file exists or `python scripts/seed_demo_data.py` is run first.

- [ ] **Step 2: Run the full test suite**

```bash
./scripts/run-tests.sh
```
Expected: all tests pass, including every test file added across Phases
1-6 (`test_registry.py`, `test_identity.py`, `test_reasoning_trace.py`,
`test_guardrails.py`, `test_demo_backend.py`, plus the extended
`test_proposals.py`).

- [ ] **Step 3: Run the demo script end to end locally**

Start the server (`uvicorn src.masova_agent.main:app --host 0.0.0.0 --port
8000 --reload`) and manually walk the readiness plan's demo beats against
`localhost:8000`: `GET /agents`, trigger 2-3 agents, a wrong-scope trigger
call rejected, an injection-style chat message rejected, `GET
/agent/runs/{run_id}` showing a reasoning trace, a proposal resolved via
`POST /agent/proposals/{id}/resolve`. Confirm each beat behaves as its
phase's spec describes.

- [ ] **Step 4: No commit for this task**

This task produces no file changes — it's a verification gate before Task
2 touches any config.

---

### Task 2: Swap to Gemini

**Files:**
- Modify: `.env` (local, gitignored — never commit)
- Modify: `config/env.example` if the default model id needs bumping

- [ ] **Step 1: Lock Gemini 3.5 Flash**

Set `.env` and `config/env.example`:

```
LLM_MODEL=gemini-3.5-flash
OPS_LLM_MODEL=gemini-3.5-flash
```

This id is the Stage 1 mandatory bar (Gemini 3.5 or newer). Do not ship
`gemini-2.5-flash`.

- [ ] **Step 2: Set the real Gemini API key**

Update `.env`: `LLM_API_KEY=<Gemini or Vertex key>`. Never commit `.env`.

- [ ] **Step 3: Re-run the full local pass against Gemini**

```bash
./scripts/run-tests.sh
```
Expected: all tests pass — this confirms the `LiteLlm`/env-driven provider
swap (`utils/config.py`, `agent.py::_resolve_model`) works with zero code
changes, and that Phase 4's guardrails / Phase 3's reasoning trace still
function against the real provider's actual response shapes (function-call
part structure can differ subtly between providers — this is the first
real test of that).

- [ ] **Step 4: Manually re-walk the demo script against Gemini**

Same walkthrough as Task 1 Step 3, now against Gemini 3.5 Flash function
calling. Watch `_extract_trace_from_event` / `run_genai_tool_loop` if the
local iteration provider's part shape differed.

---

### Task 3: Build and verify the container

**Files:**
- Modify: `Dockerfile` if it still only `COPY src/` — it must also COPY
  `scripts/seed_demo_data.py` and the console HTML, and seed SQLite into a
  writable dir on start when `DEMO_MODE=true`.

- [ ] **Step 1: Build**

```bash
docker build -t masova-enterprise-fleet:ship .
```
Expected: build succeeds without modification to `Dockerfile` or
`requirements.txt` beyond whatever Phases 1-6 already added there (none of
those 6 plans introduce a new third-party dependency beyond stdlib
`sqlite3`/`hashlib`/`re`, already part of Python 3.11).

- [ ] **Step 2: Run and health-check**

```bash
docker run --env-file .env -p 8000:8000 masova-enterprise-fleet:ship
curl localhost:8000/health
```
Expected: `{"status": "ok", "service": "masova-support-agent"}`

- [ ] **Step 3: Confirm no Dockerfile change was actually needed**

If Step 1 or 2 failed and required a `Dockerfile`/`requirements.txt`
change, that change is real work belonging to whichever phase introduced
the gap — go fix it there (e.g. `requirements.txt` if a phase's plan
missed declaring a dependency it actually uses), then return here and
re-run Steps 1-2, rather than patching around it inside this ship task.

---

### Task 4: Deploy to Cloud Run

**Files:** none in this repo — infrastructure state only.

- [ ] **Step 1: Confirm GCP credits are active**

Verify the Aug 28, 2026 credits request (noted in Global Constraints) has
been approved before spending against a personal/paid GCP account.

- [ ] **Step 2: Push secrets to Secret Manager**

```bash
gcloud secrets create llm-api-key --data-file=- <<< "$LLM_API_KEY"
gcloud secrets create jwt-secret --data-file=- <<< "$JWT_SECRET"
gcloud secrets create agent-api-keys --data-file=- <<< "$AGENT_API_KEYS"
gcloud secrets create agent-token --data-file=- <<< "$AGENT_TOKEN"
```
(Skip any secret that already exists from a prior deploy — use `gcloud
secrets versions add <name> --data-file=-` instead in that case.)

- [ ] **Step 3: Deploy**

```bash
gcloud run deploy masova-enterprise-fleet \
  --source . \
  --region <chosen-region> \
  --max-instances 1 \
  --min-instances 0 \
  --set-env-vars LLM_MODEL=gemini-3.5-flash,OPS_LLM_MODEL=gemini-3.5-flash,DEMO_MODE=true \
  --set-secrets LLM_API_KEY=llm-api-key:latest,JWT_SECRET=jwt-secret:latest,AGENT_API_KEYS=agent-api-keys:latest,AGENT_TOKEN=agent-token:latest
```
This **is** the demo backend. SQLite is instance-local, so max-instances
must stay 1. Do not deploy a second "prod" service with `DEMO_MODE=false`
for this submission — there is no MaSoVa platform on GCP to point at.

- [ ] **Step 4: Verify the deployed health endpoint**

```bash
curl https://<cloud-run-url>/health
```
Expected: same `{"status": "ok", ...}` response as Task 3 Step 2, now from
the live URL.

---

### Task 5: Record against the live `.run` URL

**Files:** none — recording setup.

- [ ] **Step 1: Confirm seed ran in the container**

Hit `GET /agent/demo/tables/inventory` on the Cloud Run URL with the
manager key. Expect mozzarella / tomato-base rows for store
`68a1f2c9e4b0a1234567890a`. If empty, the image is not seeding — fix
Dockerfile / startup (Phase 5/7 spec) and redeploy.

- [ ] **Step 2: Record the six camera beats from the constraints spec
      against `https://<service>.run.app/console`** — not localhost. Also
      show the Cloud Run dashboard or the `.run` address bar.

---

### Task 6: Domain mapping

**Files:** none in this repo.

- [ ] **Step 1: Map the domain**

```bash
gcloud run domain-mappings create --service masova-enterprise-fleet --domain <chosen-domain>
```

- [ ] **Step 2: Add the DNS records at the registrar**

Add the CNAME/A records `gcloud` outputs from Step 1 at the domain
registrar (Porkbun, per the original plan doc — confirm this is still the
registrar in use before following that reference literally).

- [ ] **Step 3: Verify**

```bash
curl https://<chosen-domain>/health
```
Expected: same health response, now via the custom domain. This step is
genuinely optional for submission — the Cloud Run URL alone satisfies the
"hosted project URL" requirement; only do this if time remains before the
Aug 31 deadline.

---

### Task 7: Public-facing provider check

**Files:**
- Verify (no modification expected): `README.md`, any docs referenced by
  the demo video script, error strings surfaced through the deployed
  `/agent/chat` and `/agents/{name}/trigger` endpoints.

- [ ] **Step 1: Grep tracked files for the local iteration provider name**

Search tracked files for the iteration-provider brand named in `CLAUDE.md`.
Expected: no matches. `.env` is gitignored.

- [ ] **Step 2: Manually trigger a deliberate error against the deployed service and inspect the response**

Send a malformed request to a live endpoint and confirm the error body
contains no provider name at all (matches `agent.py`'s existing generic
fallback message pattern — "having trouble reaching our systems," never a
provider-specific string).

- [ ] **Step 3: Confirm README, architecture diagram, and demo video script all say Gemini/Google ADK**

Read through `README.md` and `docs/ARCHITECTURE.md` end to end (note:
`docs/ARCHITECTURE.md` currently describes an outdated architecture —
in-memory mock DBs, no ADK ops runtime, no registry/identity/guardrails —
predating Phases 1-6; update it to reflect the actual shipped system before
treating it as one of the submission's required architecture-diagram
artifacts).

- [ ] **Step 4: Commit any doc corrections found**

```bash
git add README.md docs/ARCHITECTURE.md
git commit -m "docs: correct architecture doc and confirm no provider-secrecy leaks before submission"
```

(Only run this step if Step 3 actually found something to fix — if the
docs were already accurate, there's nothing to commit here.)

---

## Self-Review Notes

- **Spec coverage:** local DEMO_MODE pass (Task 1), Gemini 3.5 swap (Task 2),
  container build/verify (Task 3), Cloud Run deploy DEMO_MODE=true max-instances 1
  (Task 4), live `.run` recording (Task 5), domain mapping optional (Task 6),
  public-facing provider check (Task 7).
- **Placeholder scan:** `<chosen-region>`, `<chosen-domain>`,
  `<cloud-run-url>`, `<confirmed-model-id>` are legitimate deployment-time
  parameters (operator fills these in from real infra choices at execution
  time), not planning placeholders standing in for undecided design.
- **Type consistency:** n/a — no code interfaces in this plan.
