# Contributing

Thanks for interest in **MaSoVa Enterprise Fleet**.

## Workflow

1. Fork the repository (or use a feature branch if you have write access).
2. Create a branch from `main`: `feat/...`, `fix/...`, or `chore/...`.
3. Keep changes focused; match existing code style and HITL rules (agents propose, managers approve — never auto-execute commerce writes).
4. Run tests locally before opening a PR:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
pytest tests/ -q
```

5. Open a pull request against `main`. Fill out the PR template. Squash-merge is the default merge style.

## Public story

External-facing text (README, docs, commit messages, UI copy) must describe the stack as **Gemini** and **Google ADK**. Do not name alternate model providers or local editor tooling in tracked files.

## Secrets and local-only files

Never commit:

- `.env` or real API keys
- Demo SQLite / proposal JSONL under `/data/` (except the checked-in `data/knowledge/` corpus)
- Local editor or agent scratch directories listed in `.gitignore`
- Anything listed in `.gitignore` (ignored internal notes, mockups, QA dumps)

## Questions

Open an issue on the repository if something in the docs or runbook is unclear.
