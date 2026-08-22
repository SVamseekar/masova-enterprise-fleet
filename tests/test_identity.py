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
