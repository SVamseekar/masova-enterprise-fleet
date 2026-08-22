# Ship: Groq → Gemini → Cloud Run → Domain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Note on task shape:** unlike the other 6 phases, this plan has no code
> to TDD — it is a deployment runbook. Each task ends with a concrete,
> independently verifiable deliverable (a passing local pass, a running
> container, a live Cloud Run URL) instead of a passing test, but the same
> "no placeholders, real content only" rule applies to every step.

**Goal:** Move the fully-implemented service (Phases 1-6) from local Groq testing to a public Gemini-backed Cloud Run deployment, in the order that keeps Gemini/Cloud Run spend to the minimum needed.

**Architecture:** No code changes — only env var swaps (`LLM_API_KEY`/`LLM_MODEL`) and infrastructure commands (`docker build`, `gcloud run deploy`, `gcloud run domain-mappings create`).

**Tech Stack:** Docker, Google Cloud SDK (`gcloud`), Google Cloud Run, Secret Manager.

**Spec:** `docs/superpowers/specs/2026-08-22-ship-deployment-runbook.md`

## Global Constraints

- This plan only starts after Phases 1-6 are implemented and their test suites are green — it is not gated by this document, but by that actual state.
- Secrets (`LLM_API_KEY`, `JWT_SECRET`, `AGENT_API_KEYS`/`AGENT_TRIGGER_API_KEY`, `AGENT_TOKEN`) go through Cloud Run's Secret Manager integration — never `--set-env-vars` with plaintext.
- No response, log line, or doc visible outside this repo may say "Groq" — public-facing text says Gemini/Google ADK only (`CLAUDE.md` hard rule).
- Google Cloud credits request deadline: **Aug 28, 2026, 12:00pm PT** — this plan's Task 4 (Cloud Run deploy) cannot start after that without the credits already secured.

---

### Task 1: Full local pass on Groq

**Files:** none modified — verification only.

- [ ] **Step 1: Confirm `.env` points at Groq**

```bash
grep -E "^LLM_API_KEY|^LLM_MODEL" .env
```
Expected: `LLM_MODEL` set to the Groq model id currently used for testing
per `CLAUDE.md`'s "Actually running on Groq's free tier right now" note;
`LLM_API_KEY` non-empty.

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

- [ ] **Step 1: Confirm the Gemini model id satisfies the hackathon's mandatory-tech requirement**

Per the hackathon rules memory: "Gemini 3.5 or newer, via Gemini API or
Vertex AI." Check `config/env.example`'s current default
(`LLM_MODEL=gemini-2.5-flash`) against whatever the newest generally
available Gemini model id is at deploy time — if `2.5` doesn't satisfy "3.5
or newer," update both `.env` and `config/env.example`'s default to the
correct id before proceeding. This is a factual check against the
hackathon's stated requirement, not a judgment call — resolve it against
the actual rules page, not assumption.

- [ ] **Step 2: Set the real Gemini API key**

Update `.env`: `LLM_API_KEY=<real Gemini key>`, `LLM_MODEL=<confirmed
model id>`. Never commit `.env` — confirm `git status` shows no changes to
tracked files after this edit.

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

Same walkthrough as Task 1 Step 3, now against the real Gemini responses —
this is the first time the guardrail and reasoning-trace code paths see a
non-Groq function-calling response shape; watch specifically for any
`_extract_trace_from_event`/`run_genai_tool_loop` parsing assumption that
was implicitly tuned against Groq's response shape during Phases 3-4's
implementation.

---

### Task 3: Build and verify the container

**Files:** none modified — verification only (the existing `Dockerfile`
should need no changes, since no phase added a new system dependency).

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
  --set-env-vars LLM_MODEL=<confirmed-model-id>,DEMO_MODE=false \
  --set-secrets LLM_API_KEY=llm-api-key:latest,JWT_SECRET=jwt-secret:latest,AGENT_API_KEYS=agent-api-keys:latest,AGENT_TOKEN=agent-token:latest
```
`DEMO_MODE=false` here is deliberate — production Cloud Run should not run
against the seeded demo SQLite; the demo video's "backend running on
Google Cloud" beat needs its own explicit decision (Task 5) about whether
the recorded demo runs `DEMO_MODE=true` against this same deployed service
or a separate demo-configured revision.

- [ ] **Step 4: Verify the deployed health endpoint**

```bash
curl https://<cloud-run-url>/health
```
Expected: same `{"status": "ok", ...}` response as Task 3 Step 2, now from
the live URL.

---

### Task 5: Decide and configure the demo recording's `DEMO_MODE`

**Files:** none — infrastructure/config decision.

- [ ] **Step 1: Choose one of two options and record the choice**

Either (a) deploy a second Cloud Run revision/service with `DEMO_MODE=true`
purely for the recorded demo, seeded via `scripts/seed_demo_data.py` at
container startup, or (b) record the demo against the local Docker
container from Task 3 (which can run `DEMO_MODE=true`) while still showing
the Cloud Run dashboard/URL from Task 4 on camera to satisfy "backend
running on Google Cloud." Option (b) is simpler and matches the spec's
framing that the video needs to *show* Cloud Run running, not necessarily
have every recorded action hit the production Cloud Run instance directly.
Pick one and note the choice in `docs/hackathon/DESIGN_NOTES.md` so the
demo script (readiness plan) references the actual recording setup.

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

- [ ] **Step 1: Grep the repo for the word "Groq" outside `CLAUDE.md`**

```bash
grep -ril "groq" --exclude=CLAUDE.md --exclude-dir=.git .
```
Expected: no matches (or only matches inside `.env`/`.env.example`
comments describing the local test-path convention, which are gitignored
or intentionally provider-agnostic — verify each match individually rather
than assuming "no matches" without checking).

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

- **Spec coverage:** local Groq pass (Task 1), Gemini swap (Task 2),
  container build/verify (Task 3), Cloud Run deploy with secrets via
  Secret Manager (Task 4), domain mapping (Task 6), public-facing
  provider check (Task 7), rollback (documented in the spec, not a task
  here since it's a contingency command — `gcloud run services
  update-traffic ... --to-revisions <prev>=100` — not a scheduled step).
  Task 5 (demo `DEMO_MODE` decision) is new relative to the spec — added
  during planning because the spec's runbook didn't explicitly resolve
  which running instance the recorded demo actually hits, and that's a
  real decision the demo script depends on.
- **Placeholder scan:** `<chosen-region>`, `<chosen-domain>`,
  `<cloud-run-url>`, `<confirmed-model-id>` are legitimate deployment-time
  parameters (operator fills these in from real infra choices at execution
  time), not planning placeholders standing in for undecided design.
- **Type consistency:** n/a — no code interfaces in this plan.
