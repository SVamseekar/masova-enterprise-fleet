import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def test_rate_limit_blocks_after_budget(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "2")
    from masova_agent.runtime.rate_limit import reset_for_tests, check_rate_limit_sync
    reset_for_tests()
    assert check_rate_limit_sync("k") is True
    assert check_rate_limit_sync("k") is True
    assert check_rate_limit_sync("k") is False


def test_circuit_opens_after_three_llm_failures():
    from masova_agent.runtime.circuit import reset_for_tests, record_failure, allow_llm
    reset_for_tests()
    assert allow_llm("inventory_reorder") is True
    record_failure("inventory_reorder")
    record_failure("inventory_reorder")
    record_failure("inventory_reorder")
    assert allow_llm("inventory_reorder") is False
