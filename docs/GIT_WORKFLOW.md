# Git workflow (MaSoVa Support / Agent Service)

This repo uses **GitHub Flow** with a protected `main` and **squash merges**.

## Branching

| Prefix | Use |
|--------|-----|
| `feature/` | New behavior, agents, APIs |
| `fix/` | Bug fixes |
| `chore/` | Tooling, CI, deps, cleanup |
| `docs/` | Documentation only |
| `test/` | Test harness / fixtures |

1. Start from an up-to-date `main`:
   ```bash
   git checkout main
   git pull origin main
   git checkout -b feature/short-description
   ```
2. Open a PR targeting `main`.
3. Wait for the required CI check **`test`** (workflow job name) to pass.
4. **Squash merge** into `main` (only merge method enabled).
5. Head branch is **auto-deleted** on GitHub after merge. Prune locally:
   ```bash
   git checkout main
   git pull origin main
   git fetch --prune
   git branch -d feature/short-description   # if still present locally
   ```

## Branch protection (main)

- Pull request required (no direct push for normal work)
- **Required status check:** `test` (strict — branch must be up to date with `main`)
- Linear history (squash merges)
- No force-push, no branch deletion of `main`
- Conversation resolution required before merge
- Admins are enforced by the same rules
- Approving review count is **0** (solo maintainer); bar is **self-review + green CI**

## Commit messages

Use conventional prefixes (scope optional):

- `feat(...):` — new capability
- `fix(...):` — bug fix
- `chore(...):` — maintenance
- `test(...):` — tests
- `docs(...):` — documentation

Do **not** add `Co-Authored-By` trailers or AI-tool traces in commits.

## Never commit

- `.env` / real secrets / API keys
- `CLAUDE.md` (local-only; gitignored)
- `.claude/`, `.cursor/`, and other AI-editor workspaces
- Virtualenvs (`.venv/`), caches, coverage artifacts

Public docs and README describe **Gemini / Google ADK**. Do not put internal provider names in tracked docs or commit messages intended for public history.

## CI

- Workflow: `.github/workflows/ci.yml`
- Required check name: **`test`**
- Runs unit tests with dummy env (no live LLM or platform backend)
- Concurrency cancels outdated runs on the same ref

## Dependabot

Config: [`.github/dependabot.yml`](../.github/dependabot.yml)

| Ecosystem | Cadence | Grouping |
|-----------|---------|----------|
| `github-actions` | Weekly (Monday) | All Actions in one PR |
| `pip` | Weekly (Monday) | **Google AI stack** (`google-adk`, `google-genai`, related) in one PR; other **minor/patch** grouped; remaining **majors** individual |

- Commit prefix: `chore(deps):` (via `prefix: chore` + `include: scope`)
- Labels: `dependencies`, plus `github-actions` or `python` (create these labels if missing)
- Runtime install source of truth: **`requirements.txt`** (CI: `pip install -r requirements.txt` then `pip install -e . --no-deps`). Keep **`pyproject.toml` pins** aligned with those lower bounds.
- **`google-adk` + `google-genai` must move together** — ADK versions pin a genai range (e.g. ADK 1.28.x needs `google-genai>=1.64,<2`). Majors for both are ignored by Dependabot; upgrade deliberately in one PR.
- Also ignored majors: `redis`, `black` (noise / breaking).
- Prefer **squash-merge** only after CI `test` is green.
- **Security alerts** (GitHub → Security → Dependabot): treat as higher priority than routine bumps. Security floor today: `google-adk>=1.28.1`, `python-dotenv>=1.2.2`.
- After changing `dependabot.yml`, close conflicting ungrouped PRs; Dependabot will open fresh grouped PRs on the next schedule.

## Stale branches and archives

- Prefer auto-delete on merge; after older merges without auto-delete, remove remote branches only after verifying content is on `main` or intentionally abandoned.
- Unique WIP that is not merged may be preserved as an **archive tag** before branch delete:
  ```bash
  git tag archive/<name> <commit>
  git push origin archive/<name>
  git push origin --delete <branch>
  ```

### Known archive tags

- `archive/wip-agent-local-2026-07-09` — parked local agent/legacy snapshot from July 2026 (not on main). Inspect with `git show archive/wip-agent-local-2026-07-09`.

## Releases (optional)

When shipping a version, tag:

```text
vMAJOR.MINOR.PATCH
```

Example: `v0.1.0`. Prefer annotated tags and a short changelog entry in `CHANGELOG` / release notes. Do not retag or force-move tags that others may have pulled.

## Related docs

- [CONTRIBUTING.md](./CONTRIBUTING.md) — setup and coding standards
- [RUNBOOK.md](./RUNBOOK.md) — operations
