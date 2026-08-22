# Agent Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single shared `AGENT_TRIGGER_API_KEY` gating every internal route with per-agent scoped credentials, loaded live from `AGENT_API_KEYS`, so a leaked/misused key can only act within its granted scopes.

**Architecture:** A new `runtime/identity.py` loads a live credential list from env, exposes a `require_scope(scope)` FastAPI-dependency factory, and falls back to treating the legacy `AGENT_TRIGGER_API_KEY` as a master (`"*"`-scoped) credential when `AGENT_API_KEYS` is unset. Every gated route in `main.py` swaps `Depends(verify_trigger_api_key)` for `Depends(require_scope(...))` with the specific scope that route needs.

**Tech Stack:** Python 3.11, FastAPI.

**Spec:** `docs/superpowers/specs/2026-08-22-agent-identity-design.md`

## Global Constraints

- No hardcoding: credential-to-scope mapping loads live from `AGENT_API_KEYS` (env, JSON) at request time via `reload_config()`, never a static dict of secrets in source.
- Depends on Phase 1's `GET /agents` route already existing (`main.py`) — this plan re-gates it, doesn't create it.
- Failure behavior must not regress: missing/wrong key → 401, same as today's `verify_trigger_api_key`.
- Test import style: `from masova_agent.x import y` (no `src.` prefix).

---

### Task 1: Credential loading and scope model (`runtime/identity.py`)

**Files:**
- Create: `src/masova_agent/runtime/identity.py`
- Test: `tests/test_identity.py`

**Interfaces:**
- Consumes: `os.getenv("AGENT_API_KEYS")`, `os.getenv("AGENT_TRIGGER_API_KEY")` (existing var, `auth.py`).
- Produces: `AgentCredential` (frozen dataclass: `key: str`, `scopes: frozenset[str]`), `load_credentials() -> dict[str, AgentCredential]` — Task 2 depends on this exact signature.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_identity.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import json

from masova_agent.runtime import identity


def test_load_credentials_from_agent_api_keys_json(monkeypatch):
    monkeypatch.delenv("AGENT_TRIGGER_API_KEY", raising=False)
    monkeypatch.setenv("AGENT_API_KEYS", json.dumps([
        {"key": "master-key", "scopes": ["*"]},
        {"key": "inv-key", "scopes": ["trigger:inventory_reorder", "read:registry"]},
    ]))
    creds = identity.load_credentials()
    assert creds["master-key"].scopes == frozenset({"*"})
    assert creds["inv-key"].scopes == frozenset({"trigger:inventory_reorder", "read:registry"})


def test_load_credentials_falls_back_to_legacy_trigger_key(monkeypatch):
    monkeypatch.delenv("AGENT_API_KEYS", raising=False)
    monkeypatch.setenv("AGENT_TRIGGER_API_KEY", "legacy-key")
    creds = identity.load_credentials()
    assert creds["legacy-key"].scopes == frozenset({"*"})


def test_load_credentials_empty_when_nothing_configured(monkeypatch):
    monkeypatch.delenv("AGENT_API_KEYS", raising=False)
    monkeypatch.delenv("AGENT_TRIGGER_API_KEY", raising=False)
    creds = identity.load_credentials()
    assert creds == {}


def test_credential_has_scope_checks_wildcard():
    cred = identity.AgentCredential(key="k", scopes=frozenset({"*"}))
    assert cred.has_scope("trigger:anything")
    assert cred.has_scope("read:registry")


def test_credential_has_scope_checks_exact_match():
    cred = identity.AgentCredential(key="k", scopes=frozenset({"trigger:kitchen_coach"}))
    assert cred.has_scope("trigger:kitchen_coach")
    assert not cred.has_scope("trigger:dynamic_pricing")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_identity.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'masova_agent.runtime.identity'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/masova_agent/runtime/identity.py
"""
Per-agent scoped credentials, replacing the single shared trigger key.

Live credential source: AGENT_API_KEYS (JSON array of {"key", "scopes"}).
Falls back to treating AGENT_TRIGGER_API_KEY as one master ("*"-scoped)
credential when AGENT_API_KEYS is unset — a migration path, not a
permanent duplicate mechanism (see spec's "Loading credentials" section).

Scope kinds: "trigger:<agent_id>", "read:registry", "read:proposals",
"resolve:proposals". "*" grants all scopes.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentCredential:
    key: str
    scopes: frozenset[str]

    def has_scope(self, scope: str) -> bool:
        return "*" in self.scopes or scope in self.scopes


def load_credentials() -> dict[str, AgentCredential]:
    raw = os.getenv("AGENT_API_KEYS", "").strip()
    if raw:
        try:
            entries = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error("AGENT_API_KEYS is not valid JSON: %s", e)
            entries = []
        creds: dict[str, AgentCredential] = {}
        for entry in entries:
            key = str(entry.get("key") or "").strip()
            if not key:
                continue
            scopes = frozenset(str(s) for s in (entry.get("scopes") or []))
            creds[key] = AgentCredential(key=key, scopes=scopes)
        return creds

    legacy = os.getenv("AGENT_TRIGGER_API_KEY", "").strip()
    if legacy:
        return {legacy: AgentCredential(key=legacy, scopes=frozenset({"*"}))}

    return {}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_identity.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/masova_agent/runtime/identity.py tests/test_identity.py
git commit -m "feat: load per-agent scoped credentials, live from AGENT_API_KEYS"
```

---

### Task 2: `require_scope` FastAPI dependency factory

**Files:**
- Modify: `src/masova_agent/runtime/identity.py`
- Test: `tests/test_identity.py`

**Interfaces:**
- Consumes: `load_credentials()` (Task 1), FastAPI `Header` (same pattern as `auth.py::verify_trigger_api_key`).
- Produces: `require_scope(scope: str) -> Callable` — an async FastAPI dependency; Task 3 wires this into every gated route in `main.py`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_identity.py`:

```python
import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient


def _make_app():
    app = FastAPI()

    @app.get("/protected")
    async def protected(_: None = Depends(identity.require_scope("trigger:inventory_reorder"))):
        return {"ok": True}

    return app


def test_require_scope_rejects_missing_header(monkeypatch):
    monkeypatch.setenv("AGENT_API_KEYS", json.dumps([
        {"key": "inv-key", "scopes": ["trigger:inventory_reorder"]},
    ]))
    client = TestClient(_make_app())
    resp = client.get("/protected")
    assert resp.status_code == 401


def test_require_scope_rejects_unknown_key(monkeypatch):
    monkeypatch.setenv("AGENT_API_KEYS", json.dumps([
        {"key": "inv-key", "scopes": ["trigger:inventory_reorder"]},
    ]))
    client = TestClient(_make_app())
    resp = client.get("/protected", headers={"X-Agent-Api-Key": "wrong-key"})
    assert resp.status_code == 401


def test_require_scope_rejects_key_without_scope(monkeypatch):
    monkeypatch.setenv("AGENT_API_KEYS", json.dumps([
        {"key": "other-key", "scopes": ["trigger:kitchen_coach"]},
    ]))
    client = TestClient(_make_app())
    resp = client.get("/protected", headers={"X-Agent-Api-Key": "other-key"})
    assert resp.status_code == 401


def test_require_scope_accepts_key_with_exact_scope(monkeypatch):
    monkeypatch.setenv("AGENT_API_KEYS", json.dumps([
        {"key": "inv-key", "scopes": ["trigger:inventory_reorder"]},
    ]))
    client = TestClient(_make_app())
    resp = client.get("/protected", headers={"X-Agent-Api-Key": "inv-key"})
    assert resp.status_code == 200


def test_require_scope_accepts_master_key(monkeypatch):
    monkeypatch.setenv("AGENT_API_KEYS", json.dumps([
        {"key": "master", "scopes": ["*"]},
    ]))
    client = TestClient(_make_app())
    resp = client.get("/protected", headers={"X-Agent-Api-Key": "master"})
    assert resp.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_identity.py -v -k test_require_scope`
Expected: FAIL with `AttributeError: module 'masova_agent.runtime.identity' has no attribute 'require_scope'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/masova_agent/runtime/identity.py`:

```python
from typing import Callable

from fastapi import Header, HTTPException, status


def require_scope(scope: str) -> Callable:
    async def _dependency(x_agent_api_key: str = Header(default="")) -> None:
        if not x_agent_api_key:
            logger.warning("scope check failed: missing_key scope=%s", scope)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing API key")

        creds = load_credentials()
        cred = creds.get(x_agent_api_key)
        if cred is None:
            logger.warning("scope check failed: unknown_key scope=%s", scope)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

        if not cred.has_scope(scope):
            logger.warning("scope check failed: insufficient_scope scope=%s key=%s", scope, x_agent_api_key)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    return _dependency
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_identity.py -v`
Expected: PASS (10 tests total)

- [ ] **Step 5: Commit**

```bash
git add src/masova_agent/runtime/identity.py tests/test_identity.py
git commit -m "feat: add require_scope FastAPI dependency for per-agent authorization"
```

---

### Task 3: Wire every gated route to its specific scope

**Files:**
- Modify: `src/masova_agent/main.py` (every `Depends(verify_trigger_api_key)` on the 7 trigger routes, `GET /agents`, `GET /agent/proposals`, `POST /agent/proposals/{id}/resolve`)
- Test: `tests/test_identity.py` (append integration tests against the real app)

**Interfaces:**
- Consumes: `require_scope(scope: str)` (Task 2).
- Produces: nothing new — this task only rewires existing routes' dependencies.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_identity.py`:

```python
def test_wrong_scope_key_rejected_on_other_agent_trigger(monkeypatch):
    monkeypatch.setenv("AGENT_API_KEYS", json.dumps([
        {"key": "forecast-key", "scopes": ["trigger:demand_forecast"]},
    ]))
    from masova_agent.main import app

    client = TestClient(app)
    resp = client.post(
        "/agents/inventory-reorder/trigger",
        headers={"X-Agent-Api-Key": "forecast-key"},
    )
    assert resp.status_code == 401


def test_correct_scope_key_allowed_through_to_the_route(monkeypatch):
    monkeypatch.setenv("AGENT_API_KEYS", json.dumps([
        {"key": "inv-key", "scopes": ["trigger:inventory_reorder"]},
    ]))
    from masova_agent.main import app
    from masova_agent.runtime import proposal_store
    from masova_agent.runtime.idempotency import clear_for_tests as clear_idem

    proposal_store.clear_for_tests()
    clear_idem()

    client = TestClient(app)
    resp = client.post(
        "/agents/inventory-reorder/trigger",
        headers={"X-Agent-Api-Key": "inv-key"},
    )
    # 200/500 both prove the dependency let the request through to the
    # handler (a 401 would mean the scope check itself failed) — this repo's
    # existing agent handlers may fail without live backend config in CI,
    # so assert only that auth did not block it.
    assert resp.status_code != 401


def test_master_key_reads_registry_and_proposals(monkeypatch):
    monkeypatch.setenv("AGENT_API_KEYS", json.dumps([
        {"key": "master", "scopes": ["*"]},
    ]))
    from masova_agent.main import app

    client = TestClient(app)
    resp = client.get("/agents", headers={"X-Agent-Api-Key": "master"})
    assert resp.status_code == 200
    resp = client.get("/agent/proposals", headers={"X-Agent-Api-Key": "master"})
    assert resp.status_code == 200


def test_scoped_key_without_resolve_scope_rejected(monkeypatch):
    monkeypatch.setenv("AGENT_API_KEYS", json.dumps([
        {"key": "reader", "scopes": ["read:proposals"]},
    ]))
    from masova_agent.main import app

    client = TestClient(app)
    resp = client.post(
        "/agent/proposals/some-id/resolve",
        headers={"X-Agent-Api-Key": "reader"},
        json={"status": "APPROVED"},
    )
    assert resp.status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_identity.py -v -k "wrong_scope or correct_scope or master_key or without_resolve"`
Expected: FAIL — routes still use `verify_trigger_api_key`, so a
`forecast-key`-scoped credential (built only from `AGENT_API_KEYS`, no
wildcard) gets treated as invalid entirely by the old dependency, and the
"correct scope" test also fails since `verify_trigger_api_key` only checks
against `AGENT_TRIGGER_API_KEY`, which isn't set in this test.

- [ ] **Step 3: Rewire the routes**

In `src/masova_agent/main.py`:

1. Add the import: `from .runtime.identity import require_scope`
2. Replace each trigger route's dependency, e.g.:

```python
@app.post("/agents/demand-forecast/trigger", dependencies=[Depends(require_scope("trigger:demand_forecast"))])
async def trigger_demand_forecast():
    from .agents.demand_forecasting_agent import run_demand_forecast
    return await run_demand_forecast()
```

Apply the same substitution — only the scope string changes — to all seven
trigger routes, using these exact scope strings (matching `AGENT_ALLOWLISTS`
keys from `wrap.py`, which Phase 1's registry already relies on being
consistent):

| Route | Scope |
|---|---|
| `/agents/demand-forecast/trigger` | `trigger:demand_forecast` |
| `/agents/inventory-reorder/trigger` | `trigger:inventory_reorder` |
| `/agents/churn-prevention/trigger` | `trigger:churn_prevention` |
| `/agents/review-response/trigger` | `trigger:review_response` |
| `/agents/shift-optimisation/trigger` | `trigger:shift_optimisation` |
| `/agents/kitchen-coach/trigger` | `trigger:kitchen_coach` |
| `/agents/dynamic-pricing/trigger` | `trigger:dynamic_pricing` |

3. `GET /agents` (Phase 1's route): `dependencies=[Depends(require_scope("read:registry"))]`
4. `GET /agent/proposals`: `dependencies=[Depends(require_scope("read:proposals"))]`
5. `POST /agent/proposals/{proposal_id}/resolve`: `dependencies=[Depends(require_scope("resolve:proposals"))]`

`verify_trigger_api_key` stays defined in `auth.py` (still exported, still
used internally by `identity.load_credentials()`'s legacy fallback
conceptually, though not called directly anymore) — do not delete it, since
removing it is out of scope for this plan and other code/tests may still
reference it.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_identity.py -v`
Expected: PASS (14 tests total)

- [ ] **Step 5: Run the full test suite to check for regressions**

Run: `pytest tests/ -v --ignore=tests/test_scenarios.py`
Expected: PASS. If any pre-existing test in `tests/test_main_auth.py` or
similar asserts against `AGENT_TRIGGER_API_KEY`-only behavior, verify it
still passes because of Task 1's legacy-fallback path (`AGENT_API_KEYS`
unset → `AGENT_TRIGGER_API_KEY` becomes a master credential) — if a test
fails there, that test's setup needs `AGENT_API_KEYS` unset (not both env
vars set at once, which is unambiguous per Task 1's precedence: `AGENT_API_KEYS`
wins whenever it's non-empty).

- [ ] **Step 6: Commit**

```bash
git add src/masova_agent/main.py tests/test_identity.py
git commit -m "feat: gate every internal route with per-agent scoped credentials"
```

---

## Self-Review Notes

- **Spec coverage:** scope model (Task 1), live loading (Task 1), dependency
  factory (Task 2), route wiring for all 10 gated routes (Task 3), failure
  behavior / 401 parity (Task 2 & 3 tests), migration fallback (Task 1
  tests). Demo proof point (wrong-scope rejection) is directly covered by
  `test_wrong_scope_key_rejected_on_other_agent_trigger`.
- **Placeholder scan:** none found.
- **Type consistency:** `AgentCredential.scopes` is `frozenset[str]` used
  consistently in `load_credentials` (Task 1) and `has_scope`/`require_scope`
  (Task 2); scope string format (`"trigger:<agent_id>"`, `"read:registry"`,
  `"read:proposals"`, `"resolve:proposals"`) matches exactly between Task 2's
  tests and Task 3's route table.
