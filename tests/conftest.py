"""
Pytest configuration for masova-support tests.
"""
import os
import sys
from pathlib import Path

import pytest

# Hermetic defaults so unit tests do not require a local .env or real keys.
os.environ.setdefault("LLM_API_KEY", "test-llm-key-not-for-production")

_src = str(Path(__file__).parent.parent / "src")
# Insert at position 0 AND remove any path entry pointing at the legacy
# top-level masova_agent/ package so src/masova_agent/ always wins.
_root = str(Path(__file__).parent.parent)
if _root in sys.path:
    sys.path.remove(_root)
if _src not in sys.path:
    sys.path.insert(0, _src)

collect_ignore = ["test_scenarios.py"]


@pytest.fixture(autouse=True)
def _isolate_jsonl_stores(tmp_path, monkeypatch):
    """
    Redirect proposal/run JSONL stores to a per-test tmp dir by default.

    Without this, any test exercising an agent's rule-fallback path (which
    writes proposals/runs unconditionally, not just through mocked HTTP calls)
    falls through to the real repo-relative data/proposals/ and data/runs/
    directories and pollutes live demo data with mock store ids like "s1" /
    "store-1". A test that needs a specific PROPOSAL_DATA_DIR/RUN_DATA_DIR can
    still monkeypatch.setenv(...) after this fixture runs to override it.
    """
    monkeypatch.setenv("PROPOSAL_DATA_DIR", str(tmp_path / "proposals"))
    monkeypatch.setenv("RUN_DATA_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)

    # These modules cache a module-level "_loaded" flag plus in-memory state
    # from whichever directory loaded first in this process — reset both so
    # the new tmp-dir env vars actually take effect for this test.
    from masova_agent.runtime import proposal_store, run_store, store_registry

    proposal_store.clear_for_tests()
    run_store.clear_for_tests()
    store_registry.clear_for_tests()
    yield
    proposal_store.clear_for_tests()
    run_store.clear_for_tests()
    store_registry.clear_for_tests()
