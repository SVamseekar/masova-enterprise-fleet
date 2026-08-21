"""Production hardening: metrics, budgets, secrets redaction, EXECUTE block."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from masova_agent.runtime import metrics
from masova_agent.runtime.agent_runtime import get_runtime, reset_runtime_for_tests
from masova_agent.runtime.models import AgentRunRequest, ActionProposal, RiskTier
from masova_agent.runtime.audit import AuditLogger
from masova_agent.runtime.policy import PolicyEngine
from masova_agent.runtime.ops_llm import _json_safe, _default_max_tool_calls


@pytest.fixture(autouse=True)
def _clean():
    metrics.reset_for_tests()
    reset_runtime_for_tests()
    yield
    metrics.reset_for_tests()
    reset_runtime_for_tests()


class TestMetrics:
    @pytest.mark.asyncio
    async def test_run_increments_counters(self):
        async def fb():
            return {
                "status": "ok",
                "proposals": [{
                    "type": "T",
                    "store_id": "s",
                    "summary": "s",
                    "rationale": "r",
                }],
            }

        await get_runtime().run(
            AgentRunRequest(
                agent_name="kitchen_coach",
                trigger_type="manual",
                prefer_llm=False,
                fallback=fb,
            )
        )
        snap = metrics.snapshot()
        assert snap["kitchen_coach"]["runs_total"] >= 1
        assert snap["kitchen_coach"]["fallback_total"] >= 1
        assert snap["kitchen_coach"]["proposals_total"] >= 1


class TestBudgets:
    def test_default_max_tool_calls_bounded(self, monkeypatch):
        monkeypatch.delenv("OPS_MAX_TOOL_CALLS", raising=False)
        assert _default_max_tool_calls() == 12
        monkeypatch.setenv("OPS_MAX_TOOL_CALLS", "99")
        assert _default_max_tool_calls() == 50
        monkeypatch.setenv("OPS_MAX_TOOL_CALLS", "3")
        assert _default_max_tool_calls() == 3

    def test_context_truncation(self):
        big = {"x": "y" * 20000}
        s = _json_safe(big, limit=500)
        assert len(s) <= 520
        assert s.endswith("…")
        assert len(s) == 501  # 500 chars + ellipsis


class TestSecurity:
    def test_audit_redacts_tokens(self):
        from masova_agent.runtime.models import AgentRunResult

        audit = AuditLogger()
        result = AgentRunResult(
            agent_name="support_chat",
            trigger_type="chat",
            status="ok",
            summary="ok",
            output={"raw_token": "secret-jwt", "authorization": "Bearer x"},
        )
        # audit only logs structured fields, not full output; redact path still works
        redacted = audit._redact({"token": "abc", "safe": 1})
        assert redacted["token"] == "[REDACTED]"
        assert redacted["safe"] == 1

    def test_execute_still_blocked(self):
        pe = PolicyEngine()
        assert pe.is_allowed("patch_menu_price", ["patch_menu_price"]) is False
        assert pe.filter_allowlist(["get_order_status", "execute_refund"]) == ["get_order_status"]
