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
