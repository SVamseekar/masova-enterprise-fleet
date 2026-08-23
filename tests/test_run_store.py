import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from masova_agent.runtime import run_store


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_DATA_DIR", str(tmp_path / "runs"))
    run_store.clear_for_tests()
    yield
    run_store.clear_for_tests()


def test_get_last_run_none_when_never_run():
    assert run_store.get_last_run("inventory_reorder") is None


def test_record_run_then_get_last_run_returns_it():
    rec = {
        "agent": "inventory_reorder",
        "status": "ok",
        "used_fallback": False,
        "at": "2026-08-22T10:00:00+00:00",
        "trigger_type": "scheduled",
    }
    run_store.record_run(rec)
    last = run_store.get_last_run("inventory_reorder")
    assert last["status"] == "ok"
    assert last["used_fallback"] is False


def test_record_run_persists_across_reload(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_DATA_DIR", str(tmp_path / "runs2"))
    run_store.clear_for_tests()
    run_store.record_run({"agent": "kitchen_coach", "status": "ok", "at": "t1"})
    run_store.clear_for_tests()  # simulate cold start — forces reload from file
    last = run_store.get_last_run("kitchen_coach")
    assert last is not None
    assert last["status"] == "ok"


def test_second_record_for_same_agent_overwrites_last():
    run_store.record_run({"agent": "dynamic_pricing", "status": "ok", "at": "t1"})
    run_store.record_run({"agent": "dynamic_pricing", "status": "error", "at": "t2"})
    last = run_store.get_last_run("dynamic_pricing")
    assert last["status"] == "error"
    assert last["at"] == "t2"


def test_audit_logger_persists_via_run_store(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_DATA_DIR", str(tmp_path / "runs3"))
    run_store.clear_for_tests()

    from masova_agent.runtime.audit import AuditLogger
    from masova_agent.runtime.models import AgentRunResult

    audit = AuditLogger()
    result = AgentRunResult(
        agent_name="shift_optimisation",
        trigger_type="scheduled",
        status="ok",
        used_fallback=False,
    )
    audit.log_run(result)

    last = run_store.get_last_run("shift_optimisation")
    assert last is not None
    assert last["status"] == "ok"
    assert last["at"]  # iso timestamp stamped at log time, not at read time


def test_verify_chain_true_on_untouched_store():
    run_store.record_run({"agent": "a", "status": "ok", "at": "t1"})
    run_store.record_run({"agent": "b", "status": "ok", "at": "t2"})
    assert run_store.verify_chain() is True


def test_verify_chain_false_after_tampering(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_DATA_DIR", str(tmp_path / "runs4"))
    run_store.clear_for_tests()
    run_store.record_run({"agent": "a", "status": "ok", "at": "t1"})

    path = run_store._jsonl_path()
    lines = path.read_text(encoding="utf-8").splitlines()
    import json as _json
    row = _json.loads(lines[0])
    row["status"] = "tampered"  # content changed, record_hash NOT recomputed
    path.write_text(_json.dumps(row) + "\n", encoding="utf-8")

    run_store.clear_for_tests()  # force reload from the tampered file
    assert run_store.verify_chain() is False


def test_chain_survives_clear_for_tests_then_append(tmp_path, monkeypatch):
    """Restart/reload: clear_for_tests resets memory but leaves the file; next
    record_run must continue the on-disk chain tip, not re-genesis."""
    monkeypatch.setenv("RUN_DATA_DIR", str(tmp_path / "runs5"))
    run_store.clear_for_tests()
    run_store.record_run({"agent": "a", "status": "ok", "at": "t1"})
    run_store.record_run({"agent": "b", "status": "ok", "at": "t2"})
    run_store.clear_for_tests()  # memory reset; JSONL still on disk
    run_store.record_run({"agent": "c", "status": "ok", "at": "t3"})
    assert run_store.verify_chain() is True


def test_verify_chain_agent_filter_still_checks_global_chain(tmp_path, monkeypatch):
    """Chain is whole-file; agent_name does not create a per-agent skip path."""
    monkeypatch.setenv("RUN_DATA_DIR", str(tmp_path / "runs6"))
    run_store.clear_for_tests()
    run_store.record_run({"agent": "a", "status": "ok", "at": "t1"})
    run_store.record_run({"agent": "b", "status": "ok", "at": "t2"})
    run_store.record_run({"agent": "a", "status": "ok", "at": "t3"})
    assert run_store.verify_chain() is True
    assert run_store.verify_chain("a") is True

    path = run_store._jsonl_path()
    lines = path.read_text(encoding="utf-8").splitlines()
    import json as _json
    rows = [_json.loads(line) for line in lines if line.strip()]
    # Tamper agent-b row (middle of interleaved chain)
    rows[1]["status"] = "tampered"
    path.write_text(
        "\n".join(_json.dumps(r) for r in rows) + "\n",
        encoding="utf-8",
    )
    run_store.clear_for_tests()
    assert run_store.verify_chain("a") is False
