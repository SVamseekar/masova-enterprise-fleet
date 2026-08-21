# Contributing to MaSoVa Agent

## Git workflow

Use **GitHub Flow**: feature branch → PR → squash merge → `main`.

Full detail (branch protection, CI check name `test`, prune after merge, commit style, archive tags):

**[GIT_WORKFLOW.md](./GIT_WORKFLOW.md)**

## Development setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/SVamseekar/masova-support.git
   cd masova-support
   ```

2. **Setup environment**
   ```bash
   make setup
   # or: python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && pip install -e .
   ```

3. **Configure secrets locally (never commit)**
   ```bash
   cp .env.example .env   # if present; otherwise create root .env
   # Set GOOGLE_API_KEY / LLM_API_KEY, JWT_SECRET, BACKEND_URL, etc. only in local .env
   ```

4. **Run tests**
   ```bash
   make test
   # or: pytest tests/ -q
   ```

## Project structure

```
masova-support/
├── src/masova_agent/    # Main agent code
├── tests/               # Test files
├── scripts/             # Shell scripts
├── docs/                # Documentation
├── config/              # Configuration files
└── .venv/               # Virtual environment (gitignored)
```

## Coding standards

### Python style

- Follow PEP 8
- Use Black for formatting: `make format` (if configured)
- Run linters before committing: `make lint` (if configured)
- Type hints for public functions
- Docstrings for public APIs

### Commit messages

- `feat:` / `feat(scope):` new features  
- `fix:` bug fixes  
- `docs:` documentation  
- `chore:` tooling / maintenance  
- `test:` tests  

No `Co-Authored-By` trailers. No secrets in commits.

### Testing

- Write tests for new features  
- Prefer unit tests that mock LLM and backend  
- Run the full suite before opening a PR  

### Agents / HITL

- Agents **propose** actions; they do **not** auto-write to production DB without manager approval  
- Tool functions: `async def` returning `dict` (ADK)  

## Making changes

1. Create a branch from `main` (`feature/`, `fix/`, `chore/`, `docs/`, `test/`)
2. Make changes; keep PRs small when possible  
3. Ensure CI job **`test`** is green  
4. Squash-merge the PR  
5. Prune local branch after merge (`git fetch --prune`)  

## Questions?

Open an issue for discussion.
