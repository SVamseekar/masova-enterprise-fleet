# Ship: local LLM → Gemini 3.5 → Cloud Run — Runbook

Status: **revised 2026-08-22** (review pass). Phase 7 of 7.
Track: All Things Agentic Hackathon — The Fortified Enterprise Fleet
Inherits: [hackathon-constraints.md](./2026-08-22-hackathon-constraints.md)

This is a runbook, not an architecture change. The service shape is
unchanged. What changes: which model answers `LLM_MODEL`, and where the
process runs.

Public-facing text (README, this repo's `docs/`, commit messages, API
errors, video) says **Gemini / Google ADK only**. The local iteration
provider is named only in gitignored `CLAUDE.md`.

## Preconditions

- [ ] Phases 1–6 implemented, tests green, demo walkthrough done locally
      with `DEMO_MODE=true` against seeded SQLite
- [ ] `docs/hackathon/fleet-readiness-plan.html` no longer names the
      iteration provider, and says `masova-enterprise-fleet` (not
      `masova-support`)
- [ ] GCP **$150 credit request already submitted**. Do **not** start
      Cloud Run spend until the credit is on the billing account.
      Credits deadline: **28 Aug 2026, 12:00 PT** (request is in; wait)

## Sequence

### 1. Local pass (no GCP)

`.env`: `DEMO_MODE=true`, `LLM_API_KEY` / `LLM_MODEL` pointed at the
local iteration endpoint. `./scripts/run-tests.sh`. Walk the six camera
beats in the constraints spec against `localhost:8000` + `/console`.

### 2. Swap to Gemini 3.5 (still local)

Locked model id: **`gemini-3.5-flash`** (stable, Gemini API or Vertex).
This is the Stage 1 mandatory bar. Do not ship `gemini-2.5-flash`.

```
LLM_MODEL=gemini-3.5-flash
OPS_LLM_MODEL=gemini-3.5-flash
LLM_API_KEY=<Gemini or Vertex key>
```

Update `config/env.example` defaults to `gemini-3.5-flash`. Re-run the
local demo walk. Optional: set `GEMMA_MODEL` for the Armor bonus pass.

### 3. Container

Dockerfile **must** COPY:

- `src/`
- `scripts/seed_demo_data.py`
- `docs/hackathon/fleet-console-mockup.html` (or the static copy)
- `tests/fixtures/backend_contracts.py` only if the seed script imports it;
  otherwise keep seed data inline in the script so the image does not
  need `tests/`

Startup: if `DEMO_MODE=true` and the SQLite file is missing, run the seed
script into a writable dir (`/tmp/masova_demo.sqlite` or `/app/data/demo`
with a volume). Cloud Run is read-only except `/tmp` unless you set a
writable dir.

```
docker build -t masova-enterprise-fleet:ship .
docker run --env-file .env -e DEMO_MODE=true -p 8000:8000 masova-enterprise-fleet:ship
curl localhost:8000/health
curl localhost:8000/console | head
```

### 4. Deploy to Cloud Run (only after credits land)

One service, demo configuration — this **is** the submission backend.
SQLite is instance-local, so pin concurrency:

```
gcloud run deploy masova-enterprise-fleet \
  --source . \
  --region <chosen-region> \
  --max-instances 1 \
  --min-instances 0 \
  --set-env-vars LLM_MODEL=gemini-3.5-flash,OPS_LLM_MODEL=gemini-3.5-flash,DEMO_MODE=true \
  --set-secrets LLM_API_KEY=llm-api-key:latest,JWT_SECRET=jwt-secret:latest,AGENT_API_KEYS=agent-api-keys:latest,AGENT_TOKEN=agent-token:latest
```

Secrets never go through `--set-env-vars`. After the video is recorded,
leave min instances at 0. Judging FAQ: the app does not have to stay hot
for six weeks; the video must show Cloud Run / the `.run` URL live.

### 5. Record the video against the `.run` URL

Do not record the golden path only on localhost. Camera must show:

- Browser address bar with `*.run.app/console`
- Cloud Run dashboard or that URL
- sqlite proof: either Cloud Shell / local `gcloud run services proxy`
  plus `sqlite3` against a downloaded snapshot, **or** a tiny
  `GET /agent/demo/inventory` read-only endpoint (Phase 5/6, DEMO_MODE
  only) that returns the same rows the tools see — pick one so the
  before/after is visible without SSH folklore. Prefer a DEMO_MODE-only
  `GET /agent/demo/sql?table=inventory` gated by `read:registry` that
  runs a **fixed allowlisted SELECT** (no arbitrary SQL).

### 6. Domain mapping (optional)

Cloud Run URL is enough. Custom domain last, only if time remains.

### 7. Public-facing check

Search tracked files for the iteration-provider brand named in gitignored
`CLAUDE.md`. Expected: zero hits. README, architecture diagram, video
narration: Gemini 3.5, Google ADK, Cloud Run, DEMO_MODE SQLite stand-in
for the restaurant platform (disclosed, not faked as the Dell host).

### 8. Submission pack (same phase, required)

- README: clone, `DEMO_MODE=true`, seed, uvicorn, `/console`, test cmd
- Architecture diagram (replace stale `docs/ARCHITECTURE.md`) showing
  Gemini 3.5 → FastAPI/ADK → tools → SQLite (demo) / MaSoVa HTTP (not
  hosted)
- Disclose pre-existing `masova-support` code (already in README)
- Bonus: blog + social `#AllThingsAgenticHackathon` + Gemma pass
- Grant repo access if private: `testing@devpost.com`,
  `cloudhackathons@google.com`

## Rollback

`gcloud run services update-traffic masova-enterprise-fleet --to-revisions <prev>=100`

## Out of scope

- Blue/green, load tests, keeping Cloud Run hot through 1 Oct
- Hosting MaSoVa microservices
