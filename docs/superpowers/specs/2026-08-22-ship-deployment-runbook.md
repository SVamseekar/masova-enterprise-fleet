# Ship: Groq → Gemini → Cloud Run → Domain — Runbook

Status: draft (auto-authored per user instruction to proceed through all 7 phases without per-decision confirmation)
Track: All Things Agentic Hackathon — The Fortified Enterprise Fleet
Pillar: 1, 2, 3 (closes the loop on all three)
Depends on: Phases 1–6 complete and green locally on Groq

## Why this is last, and why it's a runbook not a design spec

Nothing about hosting changes the system's shape — it's the same FastAPI
service, same `Dockerfile`, same code, with two things flipped at the end:
which LLM provider answers `LLM_API_KEY`/`LLM_MODEL`, and where the process
runs. Doing this last means every phase above is proven cheaply and
quickly against Groq before spending any Gemini quota or Cloud Run minutes
on iteration.

This is a checklist, not an architecture — nothing here is a design
decision left open; it's the literal sequence of operator actions.

## Preconditions before starting this phase

- [ ] Phases 1–6 implemented, tests green, demo script walkthrough done
      locally with `LLM_API_KEY` pointed at Groq
- [ ] `docs/hackathon/fleet-readiness-plan.html`'s stale repo/domain
      references (still says `masova-support` / `masova-support.souravamseekar.com`)
      corrected to `masova-enterprise-fleet` before this doc is treated as
      final — noted as unresolved in memory as of 2026-08-22
- [ ] Google Cloud credits request submitted — **hard deadline Aug 28,
      2026, 12:00pm PT**, before this phase can spend real Cloud Run budget

## Sequence

### 1. Full local pass on Groq (already the default per `CLAUDE.md`)

Confirm `.env` has `LLM_API_KEY`/`LLM_MODEL` pointed at Groq, run the full
suite (`scripts/run-tests.sh`) and the demo script end to end locally.
Nothing in this step touches Google Cloud.

### 2. Swap to Gemini

Change only `.env` (local) or the Cloud Run env vars (deployed) —
`LLM_MODEL=gemini-2.5-flash` (or newer per the hackathon's "Gemini 3.5 or
newer" mandatory-tech requirement — confirm the exact model id satisfies
that bar before this step, since `config/env.example`'s current default of
`gemini-2.5-flash` predates that requirement and may need bumping),
`LLM_API_KEY`=a real Gemini API key. No code changes — this is the entire
point of the `LiteLlm`/env-driven provider design already in place
(`utils/config.py`, `agent.py::_resolve_model`). Re-run the same local pass
against Gemini before deploying anything, so the first live Gemini call
isn't also the first time this code path has run.

### 3. Build and verify the container

```
docker build -t masova-enterprise-fleet:ship .
docker run --env-file .env -p 8000:8000 masova-enterprise-fleet:ship
curl localhost:8000/health
```
Confirms the existing `Dockerfile`'s `HEALTHCHECK` and non-root user setup
work unchanged — nothing in Phases 1–6 should require Dockerfile changes
since none of them added new system dependencies.

### 4. Deploy to Cloud Run

```
gcloud run deploy masova-enterprise-fleet \
  --source . \
  --region <chosen-region> \
  --set-env-vars <non-secret vars> \
  --set-secrets <LLM_API_KEY etc. from Secret Manager, not plaintext env>
```
Secrets (`LLM_API_KEY`, `JWT_SECRET`, `AGENT_TRIGGER_API_KEY`/`AGENT_API_KEYS`,
`AGENT_TOKEN`) go through Cloud Run's Secret Manager integration, not
`--set-env-vars` — the same "never in tracked files" rule `CLAUDE.md`
already states for local `.env`, carried into the deploy step.

### 5. Domain mapping

```
gcloud run domain-mappings create --service masova-enterprise-fleet --domain <chosen-domain>
```
DNS records added at the registrar. This step is genuinely last — no other
phase depends on the domain being live; the demo video only needs the
Cloud Run URL and dashboard to be visible on camera per the submission's
"Proof of Action" requirement, not a custom domain.

### 6. Public-facing check (repeats a `CLAUDE.md` hard rule, here because it's easy to violate at exactly this step)

- [ ] No API error string, log line visible in a demo recording, or
      response body says "Groq" anywhere, now that traffic may briefly run
      on Groq under a public URL during earlier testing of this same
      pipeline
- [ ] README, architecture diagram, and demo video all say Gemini / Google
      ADK, never the test-path provider

## Rollback

Cloud Run keeps prior revisions by default — `gcloud run services
update-traffic masova-enterprise-fleet --to-revisions <prev-revision>=100`
reverts without a rebuild if the Gemini swap or a deploy regresses
something the local Groq pass didn't catch.

## Out of scope

- Blue/green or canary traffic splitting — single-revision cutover is
  enough for a hackathon submission's traffic profile
- Autoscaling tuning beyond Cloud Run defaults — no load-testing requirement
  in the rubric
