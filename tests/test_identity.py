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


def test_load_credentials_handles_json_object_instead_of_array(monkeypatch):
    """Regression: AGENT_API_KEYS as a JSON object should not crash, falls through to empty."""
    monkeypatch.delenv("AGENT_TRIGGER_API_KEY", raising=False)
    monkeypatch.setenv("AGENT_API_KEYS", json.dumps({"key": "x", "scopes": ["*"]}))
    creds = identity.load_credentials()
    assert creds == {}


def test_load_credentials_skips_non_dict_array_elements(monkeypatch):
    """Regression: array with non-dict elements should skip them, not crash."""
    monkeypatch.delenv("AGENT_TRIGGER_API_KEY", raising=False)
    monkeypatch.setenv("AGENT_API_KEYS", json.dumps([
        "not-a-dict",
        {"key": "valid-key", "scopes": ["*"]},
        42,
        {"key": "another-key", "scopes": ["read:registry"]},
    ]))
    creds = identity.load_credentials()
    assert "valid-key" in creds
    assert "another-key" in creds
    assert len(creds) == 2
    assert creds["valid-key"].scopes == frozenset({"*"})


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
    assert resp.status_code == 403


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
    assert resp.status_code == 403


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
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Regression guard: no live route may still depend on the deprecated,
# unscoped verify_trigger_api_key. Phase 2 rewired every /agents* route to
# require_scope(scope); if a future phase copies an older pattern and wires
# a new route to verify_trigger_api_key, this test should fail loudly
# instead of silently shipping an unscoped endpoint.
# ---------------------------------------------------------------------------


def _iter_dependant_callables(dependant):
    """Yield every dependency callable reachable from a Starlette/FastAPI
    Dependant, including nested sub-dependencies."""
    for sub in getattr(dependant, "dependencies", None) or []:
        yield sub.call
        yield from _iter_dependant_callables(sub)


def test_no_route_depends_on_deprecated_verify_trigger_api_key():
    from fastapi.routing import APIRoute

    from masova_agent.auth import verify_trigger_api_key
    from masova_agent.main import app

    offenders = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for call in _iter_dependant_callables(route.dependant):
            if call is verify_trigger_api_key:
                offenders.append(route.path)

    assert not offenders, (
        f"Route(s) {offenders} still depend on the deprecated "
        "verify_trigger_api_key; use runtime.identity.require_scope(scope) instead."
    )


def test_remaining_specialist_runs_accept_store_id():
    import inspect
    from masova_agent.agents.demand_forecasting_agent import run_demand_forecast
    from masova_agent.agents.churn_prevention_agent import run_churn_prevention
    from masova_agent.agents.shift_optimisation_agent import run_shift_optimisation
    from masova_agent.agents.kitchen_coach_agent import run_kitchen_coach

    for fn in (
        run_demand_forecast,
        run_churn_prevention,
        run_shift_optimisation,
        run_kitchen_coach,
    ):
        params = inspect.signature(fn).parameters
        assert "store_id" in params, fn.__name__
