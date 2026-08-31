## Summary

What this change does and why it belongs on `main`.

## Test plan

- [ ] `pytest tests/ -q` is green, or CI job `test` is green
- [ ] Operator / smoke steps (if the change touches `/console`, proposals, or agents):

## Risk / HITL

Agents **propose**. Managers **approve**. Nothing in this change may auto-write purchase orders, prices, refunds, campaigns, or rotas.

- [ ] No agent auto-write to the system of record
- [ ] N/A (documentation, CI, or chore only)

## Checklist

- [ ] No secrets, `.env`, or files listed in `.gitignore`
- [ ] Commit messages use `feat|fix|chore|test|docs(...):` — no `Co-Authored-By`
- [ ] Docs updated if behaviour, auth, or operator workflow changed
- [ ] Public copy names **Gemini** and **Google ADK** only
