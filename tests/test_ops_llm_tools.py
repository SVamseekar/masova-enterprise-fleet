"""Ops LLM tool-loop tests (no live LLM / no live backend)."""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from masova_agent.runtime import (
    AgentRunRequest,
    AgentRuntime,
    PolicyEngine,
    RiskTier,
    make_ops_llm_runner,
    run_scripted_tool_loop,
)
from masova_agent.runtime.agent_runtime import reset_runtime_for_tests
from masova_agent.runtime.ops_llm import (
    ops_prefer_llm,
    extract_proposals_from_tool_results,
    run_genai_tool_loop,
)
from masova_agent.runtime.policy import DEFAULT_TOOL_REGISTRY
from masova_agent.runtime.wrap import AGENT_ALLOWLISTS, run_ops_agent
from masova_agent.tools import ops_tools


@pytest.fixture(autouse=True)
def _reset():
    reset_runtime_for_tests()
    yield
    reset_runtime_for_tests()


# ---------------------------------------------------------------------------
# Policy / allowlists
# ---------------------------------------------------------------------------

class TestOpsAllowlists:
    def test_no_execute_on_any_ops_allowlist(self):
        pe = PolicyEngine()
        for agent, tools in AGENT_ALLOWLISTS.items():
            cleaned = pe.filter_allowlist(tools)
            assert cleaned == pe.filter_allowlist(cleaned)
            for t in tools:
                assert pe.tier_for(t) != RiskTier.EXECUTE, f"{agent}:{t}"
            assert "patch_menu_price" not in tools

    def test_pricing_has_propose_not_patch(self):
        tools = AGENT_ALLOWLISTS["dynamic_pricing"]
        assert "propose_price_suggestion" in tools or "suggest_price_adjustment" in tools
        assert "patch_menu_price" not in tools
        assert DEFAULT_TOOL_REGISTRY["patch_menu_price"].tier == RiskTier.EXECUTE

    def test_inventory_tools_registered(self):
        for name in ("list_low_stock", "create_draft_po", "notify_managers"):
            assert name in DEFAULT_TOOL_REGISTRY
            assert DEFAULT_TOOL_REGISTRY[name].tier != RiskTier.EXECUTE


# ---------------------------------------------------------------------------
# COMPUTE tools (pure)
# ---------------------------------------------------------------------------

class TestComputeTools:
    @pytest.mark.asyncio
    async def test_wma_forecast(self):
        r = await ops_tools.compute_wma_forecast(series=[10, 20, 30])
        assert r["ok"] is True
        assert r["forecast"] > 20  # recent-weighted

    @pytest.mark.asyncio
    async def test_pricing_signal_overload(self):
        r = await ops_tools.compute_pricing_signal(
            "s1", active_count=20, recent_count=10, current_hour=12
        )
        assert r["signal"] == "overload"
        assert r["suggested_pct"] <= 12

    @pytest.mark.asyncio
    async def test_pricing_signal_none(self):
        r = await ops_tools.compute_pricing_signal(
            "s1", active_count=5, recent_count=10, current_hour=12
        )
        assert r["signal"] == "none"

    @pytest.mark.asyncio
    async def test_price_suggestion_caps_and_no_patch(self, monkeypatch):
        monkeypatch.setenv("AGENT_TOKEN", "test-token")
        with patch.object(ops_tools, "notify_managers", new_callable=AsyncMock) as nm:
            nm.return_value = {"ok": True, "sent": 1, "proposal": {}}
            r = await ops_tools.propose_price_suggestion(
                store_id="s1",
                direction="increase",
                percent=50,  # over cap
                item_names=["Dosa"],
                rationale="20 active orders",
                active_count=20,
            )
        assert r.get("patches_menu") is False
        assert r["proposal"]["type"] == "SUGGEST_PRICE_ADJUSTMENT"
        assert r["proposal"]["requires_approval"] is True
        assert r["proposal"]["payload"]["percent"] <= 12
        assert r["proposal"]["payload"]["patches_menu"] is False


# ---------------------------------------------------------------------------
# Platform path contracts
# ---------------------------------------------------------------------------

class TestOpsToolPathContracts:
    @pytest.mark.asyncio
    async def test_forecast_reads_bi_demand_forecast_path(self, monkeypatch):
        monkeypatch.setenv("AGENT_TOKEN", "test-token")

        async def fake_get_json(client, path: str, *, params=None):
            assert path == "/api/bi"
            assert params == {"storeId": "s1", "hours": 24, "type": "demand-forecast"}
            return 200, {"forecasts": [{"itemId": "inv-1", "forecast": 42.5, "date": "2026-08-23"}]}

        with patch.object(ops_tools, "get_json", side_effect=fake_get_json):
            result = await ops_tools.get_forecast_snippet("s1")

        assert result["ok"] is True
        assert result["forecasts"][0]["predicted_qty"] == 42.5

    @pytest.mark.asyncio
    async def test_top_items_reads_analytics_top_products_path(self, monkeypatch):
        monkeypatch.setenv("AGENT_TOKEN", "test-token")

        async def fake_get_json(client, path: str, *, params=None):
            assert path == "/api/analytics"
            assert params == {"storeId": "s1", "type": "top-products"}
            return 200, {"items": [{"id": "m1", "name": "Masala Dosa", "volume": 8}]}

        with patch.object(ops_tools, "get_json", side_effect=fake_get_json):
            result = await ops_tools.get_top_items("s1")

        assert result["ok"] is True
        assert result["items"][0]["name"] == "Masala Dosa"

    @pytest.mark.asyncio
    async def test_kitchen_metrics_reads_orders_analytics_path(self, monkeypatch):
        monkeypatch.setenv("AGENT_TOKEN", "test-token")

        async def fake_get_json(client, path: str, *, params=None):
            assert path == "/api/orders/analytics"
            assert params == {"storeId": "s1", "period": "today", "type": "kitchen-metrics"}
            return 200, {"avgPrepTimeMinutes": 19, "ticketCount": 44, "slowTickets": 3}

        with patch.object(ops_tools, "get_json", side_effect=fake_get_json):
            result = await ops_tools.read_kitchen_metrics("s1")

        assert result["ok"] is True
        assert result["ticket_count"] == 44

    @pytest.mark.asyncio
    async def test_create_draft_po_uses_create_endpoint_with_draft_status(self, monkeypatch):
        monkeypatch.setenv("AGENT_TOKEN", "test-token")

        async def fake_post_json(client, path: str, payload: dict):
            assert path == "/api/purchase-orders"
            assert payload["status"] == "DRAFT"
            assert payload["items"][0]["itemName"] == "Flour"
            return 201, {"id": "po-1", "status": "DRAFT"}

        with patch.object(ops_tools, "post_json", side_effect=fake_post_json):
            result = await ops_tools.create_draft_po(
                store_id="s1",
                supplier_id="sup-1",
                items=[{"id": "inv-1", "item_name": "Flour", "quantity": 5}],
            )

        assert result["ok"] is True
        assert result["http_status"] == 201


# ---------------------------------------------------------------------------
# Scripted multi-step loops (inventory + pricing golden)
# ---------------------------------------------------------------------------

class TestInventoryToolLoop:
    @pytest.mark.asyncio
    async def test_scripted_inventory_draft_path(self):
        calls = []

        async def list_low_stock(store_id: str = ""):
            calls.append("list_low_stock")
            return {
                "ok": True,
                "items": [{
                    "id": "inv-1",
                    "store_id": "s1",
                    "item_name": "Flour",
                    "reorder_quantity": 25,
                    "primary_supplier_id": "sup-1",
                    "unit_cost": 2.5,
                }],
            }

        async def get_forecast_snippet(store_id: str, item_id: str = "", hours: int = 24):
            calls.append("get_forecast_snippet")
            return {"ok": True, "forecasts": [{"item_id": "inv-1", "predicted_qty": 18}]}

        async def create_draft_po(store_id: str, supplier_id: str, items=None, rationale: str = "", notes: str = ""):
            calls.append("create_draft_po")
            return {
                "ok": True,
                "http_status": 201,
                "proposal": {
                    "type": "DRAFT_PURCHASE_ORDER",
                    "store_id": store_id,
                    "summary": f"Draft PO flour via {supplier_id}",
                    "rationale": rationale or "Low stock vs forecast 18",
                    "risk": "PROPOSE",
                    "requires_approval": True,
                    "payload": {"items": items, "supplier_id": supplier_id},
                },
            }

        async def notify_managers(store_id: str, message: str, title: str = "", **kwargs):
            calls.append("notify_managers")
            return {
                "ok": True,
                "sent": 1,
                "proposal": {
                    "type": "NOTIFY_MANAGERS",
                    "store_id": store_id,
                    "summary": title or "notify",
                    "rationale": kwargs.get("rationale") or message,
                    "risk": "PROPOSE",
                    "requires_approval": True,
                    "payload": {"sent": 1},
                },
            }

        tools = {
            "list_low_stock": list_low_stock,
            "get_forecast_snippet": get_forecast_snippet,
            "create_draft_po": create_draft_po,
            "notify_managers": notify_managers,
        }
        plan = [
            {"tool": "list_low_stock", "args": {"store_id": "s1"}},
            {"tool": "get_forecast_snippet", "args": {"store_id": "s1", "item_id": "inv-1"}},
            {
                "tool": "create_draft_po",
                "args": {
                    "store_id": "s1",
                    "supplier_id": "sup-1",
                    "items": [{"id": "inv-1", "quantity": 25, "item_name": "Flour"}],
                    "rationale": "Stock low; forecast demand 18 units/24h",
                },
            },
            {
                "tool": "notify_managers",
                "args": {
                    "store_id": "s1",
                    "message": "Draft PO for Flour ready",
                    "title": "Inventory Reorder",
                    "rationale": "Stock low; forecast demand 18 units/24h",
                },
            },
        ]
        req = AgentRunRequest(
            agent_name="inventory_reorder",
            trigger_type="manual",
            store_id="s1",
            allowed_tools=list(AGENT_ALLOWLISTS["inventory_reorder"]),
            max_tool_calls=12,
        )
        out = await run_scripted_tool_loop(req, plan, tools)
        assert out["status"] == "ok"
        assert "list_low_stock" in out["tools_used"]
        assert "create_draft_po" in out["tools_used"]
        assert any(p["type"] == "DRAFT_PURCHASE_ORDER" for p in out["proposals"])
        assert out["proposals"][0]["rationale"]
        assert all(p.get("requires_approval", True) for p in out["proposals"])

        # Through full runtime
        runtime = AgentRuntime()
        runner = make_ops_llm_runner(
            instruction="test",
            tool_names=list(tools.keys()),
            tool_functions=tools,
            scripted_plan=plan,
        )
        result = await runtime.run(AgentRunRequest(
            agent_name="inventory_reorder",
            trigger_type="manual",
            allowed_tools=list(tools.keys()),
            prefer_llm=True,
            llm_runner=runner,
            fallback=lambda: {"status": "should_not_run"},
        ))
        assert result.used_fallback is False
        assert result.status == "ok"
        assert any(p.type == "DRAFT_PURCHASE_ORDER" for p in result.proposals)
        assert result.proposals[0].requires_approval is True
        audit = runtime.audit.records[-1]
        assert "create_draft_po" in audit["tools_used"] or "list_low_stock" in audit["tools_used"]

    @pytest.mark.asyncio
    async def test_scripted_tool_loop_produces_reasoning_trace(self):
        # Reuse this file's existing plan/tools fixtures for the low-stock
        # scenario (see the existing test above this one for the exact
        # request/plan/tools construction already used in this file).
        async def list_low_stock(store_id: str = ""):
            return {
                "ok": True,
                "items": [{
                    "id": "inv-1",
                    "store_id": "s1",
                    "item_name": "Flour",
                    "reorder_quantity": 25,
                    "primary_supplier_id": "sup-1",
                    "unit_cost": 2.5,
                }],
            }

        async def get_forecast_snippet(store_id: str, item_id: str = "", hours: int = 24):
            return {"ok": True, "forecasts": [{"item_id": "inv-1", "predicted_qty": 18}]}

        async def create_draft_po(store_id: str, supplier_id: str, items=None, rationale: str = "", notes: str = ""):
            return {
                "ok": True,
                "http_status": 201,
                "proposal": {
                    "type": "DRAFT_PURCHASE_ORDER",
                    "store_id": store_id,
                    "summary": f"Draft PO flour via {supplier_id}",
                    "rationale": rationale or "Low stock vs forecast 18",
                    "risk": "PROPOSE",
                    "requires_approval": True,
                    "payload": {"items": items, "supplier_id": supplier_id},
                },
            }

        async def notify_managers(store_id: str, message: str, title: str = "", **kwargs):
            return {
                "ok": True,
                "sent": 1,
                "proposal": {
                    "type": "NOTIFY_MANAGERS",
                    "store_id": store_id,
                    "summary": title or "notify",
                    "rationale": kwargs.get("rationale") or message,
                    "risk": "PROPOSE",
                    "requires_approval": True,
                    "payload": {"sent": 1},
                },
            }

        tools = {
            "list_low_stock": list_low_stock,
            "get_forecast_snippet": get_forecast_snippet,
            "create_draft_po": create_draft_po,
            "notify_managers": notify_managers,
        }
        plan = [
            {"tool": "list_low_stock", "args": {"store_id": "s1"}},
            {"tool": "get_forecast_snippet", "args": {"store_id": "s1", "item_id": "inv-1"}},
            {
                "tool": "create_draft_po",
                "args": {
                    "store_id": "s1",
                    "supplier_id": "sup-1",
                    "items": [{"id": "inv-1", "quantity": 25, "item_name": "Flour"}],
                    "rationale": "Stock low; forecast demand 18 units/24h",
                },
            },
            {
                "tool": "notify_managers",
                "args": {
                    "store_id": "s1",
                    "message": "Draft PO for Flour ready",
                    "title": "Inventory Reorder",
                    "rationale": "Stock low; forecast demand 18 units/24h",
                },
            },
        ]
        request = AgentRunRequest(
            agent_name="inventory_reorder",
            trigger_type="manual",
            store_id="s1",
            allowed_tools=list(AGENT_ALLOWLISTS["inventory_reorder"]),
            max_tool_calls=12,
        )
        result = await run_scripted_tool_loop(request, plan, tools)
        trace = result["reasoning_trace"]
        assert len(trace) == len(result["tools_used"])
        assert trace[0]["index"] == 0
        assert trace[0]["tool_name"] == result["tools_used"][0]
        assert trace[0]["result_status"] == "ok"
        assert trace[0]["duration_ms"] >= 0
        assert trace[0]["result_summary"]  # non-empty — real data from the tool's actual return value
        assert "Flour" in trace[0]["result_summary"]
        assert "25" in trace[0]["result_summary"]
        assert len(trace[0]["result_summary"]) <= 500
        assert [step["tool_name"] for step in trace] == result["tools_used"]
        assert [step["index"] for step in trace] == list(range(len(trace)))

    @pytest.mark.asyncio
    async def test_scripted_tool_loop_records_raised_tool_as_error(self):
        async def boom(store_id: str = ""):
            raise RuntimeError("stock feed down")

        tools = {"list_low_stock": boom}
        plan = [{"tool": "list_low_stock", "args": {"store_id": "s1"}}]
        request = AgentRunRequest(
            agent_name="inventory_reorder",
            trigger_type="manual",
            store_id="s1",
            allowed_tools=["list_low_stock"],
        )
        result = await run_scripted_tool_loop(request, plan, tools)
        trace = result["reasoning_trace"]
        assert len(trace) == 1
        assert trace[0]["tool_name"] == "list_low_stock"
        assert trace[0]["result_status"] == "error"
        assert "stock feed down" in trace[0]["result_summary"]
        assert trace[0]["duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_inventory_fallback_when_llm_raises(self):
        async def boom(req):
            raise RuntimeError("provider down")

        async def fb():
            return {"status": "ok", "pos_drafted": 1, "summary": "rule drafted 1 PO"}

        result = await AgentRuntime().run(AgentRunRequest(
            agent_name="inventory_reorder",
            trigger_type="scheduled",
            prefer_llm=True,
            llm_runner=boom,
            fallback=fb,
        ))
        assert result.used_fallback is True
        assert result.status == "ok"
        assert result.proposals


class TestPricingToolLoop:
    @pytest.mark.asyncio
    async def test_scripted_pricing_propose_only(self):
        async def compute_pricing_signal(store_id: str, **kwargs):
            return {
                "ok": True,
                "signal": "overload",
                "store_id": store_id,
                "active_count": 22,
                "suggested_pct": 12,
                "direction": "increase",
            }

        async def get_top_items(store_id: str, limit: int = 5):
            return {"ok": True, "items": [{"id": "m1", "name": "Masala Dosa", "price": 120}]}

        async def propose_price_suggestion(**kwargs):
            return {
                "ok": True,
                "patches_menu": False,
                "sent": 1,
                "proposal": {
                    "type": "SUGGEST_PRICE_ADJUSTMENT",
                    "store_id": kwargs.get("store_id", "s1"),
                    "summary": "increase 12% on Masala Dosa",
                    "rationale": kwargs.get("rationale") or "22 active orders",
                    "risk": "PROPOSE",
                    "requires_approval": True,
                    "payload": {
                        "percent": min(abs(float(kwargs.get("percent", 12))), 12),
                        "patches_menu": False,
                        "direction": "increase",
                    },
                },
            }

        tools = {
            "compute_pricing_signal": compute_pricing_signal,
            "get_top_items": get_top_items,
            "propose_price_suggestion": propose_price_suggestion,
        }
        plan = [
            {"tool": "compute_pricing_signal", "args": {"store_id": "s1"}},
            {"tool": "get_top_items", "args": {"store_id": "s1", "limit": 5}},
            {
                "tool": "propose_price_suggestion",
                "args": {
                    "store_id": "s1",
                    "direction": "increase",
                    "percent": 12,
                    "item_names": ["Masala Dosa"],
                    "rationale": "Overload: 22 active orders",
                    "active_count": 22,
                },
            },
        ]
        runner = make_ops_llm_runner(
            instruction="pricing",
            tool_names=list(tools.keys()),
            tool_functions=tools,
            scripted_plan=plan,
        )
        # Bypass pre_gate by using runner directly
        result = await AgentRuntime().run(AgentRunRequest(
            agent_name="dynamic_pricing",
            trigger_type="scheduled",
            allowed_tools=list(tools.keys()),
            prefer_llm=True,
            llm_runner=runner,
            fallback=lambda: {"status": "fallback"},
        ))
        assert result.used_fallback is False
        assert result.proposals[0].type == "SUGGEST_PRICE_ADJUSTMENT"
        assert result.proposals[0].payload.get("patches_menu") is False
        assert "patch_menu" not in str(result.tools_used).lower()

    @pytest.mark.asyncio
    async def test_pricing_pre_gate_skips_llm_when_no_signal(self):
        from masova_agent.agents.dynamic_pricing_agent import _pricing_pre_gate

        req = AgentRunRequest(
            agent_name="dynamic_pricing",
            trigger_type="scheduled",
            context={"pricing_signal": "none"},
        )
        gate = await _pricing_pre_gate(req)
        assert gate is not None
        assert gate.get("skipped_llm") is True
        assert gate.get("suggestions_sent") == 0

    @pytest.mark.asyncio
    async def test_pricing_fallback_on_llm_error(self):
        async def boom(req):
            raise RuntimeError("no model")

        async def fb():
            return {
                "status": "ok",
                "suggestions_sent": 1,
                "stores_evaluated": 1,
                "summary": "rule pricing",
            }

        result = await AgentRuntime().run(AgentRunRequest(
            agent_name="dynamic_pricing",
            trigger_type="scheduled",
            prefer_llm=True,
            llm_runner=boom,
            fallback=fb,
        ))
        assert result.used_fallback is True
        assert result.status == "ok"


class TestGenaiToolLoop:
    @pytest.mark.asyncio
    async def test_genai_tool_loop_produces_reasoning_trace(self):
        async def list_low_stock(store_id: str = ""):
            return {
                "ok": True,
                "items": [{"item_name": "Flour", "reorder_quantity": 25}],
            }

        tools = {"list_low_stock": list_low_stock}
        schemas = {
            "list_low_stock": {
                "description": "List low-stock items",
                "parameters": {
                    "type": "object",
                    "properties": {"store_id": {"type": "string"}},
                },
            }
        }
        request = AgentRunRequest(
            agent_name="inventory_reorder",
            trigger_type="manual",
            store_id="s1",
            allowed_tools=["list_low_stock"],
            max_tool_calls=4,
        )

        def _fn_call_response():
            fc = MagicMock()
            fc.name = "list_low_stock"
            fc.args = {"store_id": "s1"}
            part = MagicMock()
            part.function_call = fc
            part.text = None
            content = MagicMock()
            content.parts = [part]
            candidate = MagicMock()
            candidate.content = content
            response = MagicMock()
            response.candidates = [candidate]
            return response

        def _final_text_response():
            part = MagicMock()
            part.function_call = None
            part.text = "Draft PO ready for review"
            content = MagicMock()
            content.parts = [part]
            candidate = MagicMock()
            candidate.content = content
            response = MagicMock()
            response.candidates = [candidate]
            return response

        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = [
            _fn_call_response(),
            _final_text_response(),
        ]

        with patch("google.genai.Client", return_value=mock_client):
            result = await run_genai_tool_loop(
                request,
                instruction="Use tools; propose drafts only.",
                tools=tools,
                tool_schemas=schemas,
                api_key="test-key",
            )

        trace = result["reasoning_trace"]
        assert len(trace) == 1
        assert trace[0]["index"] == 0
        assert trace[0]["tool_name"] == "list_low_stock"
        assert trace[0]["args"] == {"store_id": "s1"}
        assert trace[0]["result_status"] == "ok"
        assert trace[0]["duration_ms"] >= 0
        assert "Flour" in trace[0]["result_summary"]
        assert "25" in trace[0]["result_summary"]
        assert len(trace[0]["result_summary"]) <= 500

    @pytest.mark.asyncio
    async def test_genai_tool_loop_records_raised_tool_as_error(self):
        async def boom(store_id: str = ""):
            raise RuntimeError("stock feed down")

        tools = {"list_low_stock": boom}
        schemas = {
            "list_low_stock": {
                "description": "List low-stock items",
                "parameters": {"type": "object", "properties": {}},
            }
        }
        request = AgentRunRequest(
            agent_name="inventory_reorder",
            trigger_type="manual",
            allowed_tools=["list_low_stock"],
            max_tool_calls=4,
        )

        fc = MagicMock()
        fc.name = "list_low_stock"
        fc.args = {"store_id": "s1"}
        part = MagicMock()
        part.function_call = fc
        part.text = None
        content = MagicMock()
        content.parts = [part]
        candidate = MagicMock()
        candidate.content = content
        fn_response = MagicMock()
        fn_response.candidates = [candidate]

        text_part = MagicMock()
        text_part.function_call = None
        text_part.text = "tool failed"
        text_content = MagicMock()
        text_content.parts = [text_part]
        text_candidate = MagicMock()
        text_candidate.content = text_content
        text_response = MagicMock()
        text_response.candidates = [text_candidate]

        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = [fn_response, text_response]

        with patch("google.genai.Client", return_value=mock_client):
            result = await run_genai_tool_loop(
                request,
                instruction="Use tools.",
                tools=tools,
                tool_schemas=schemas,
                api_key="test-key",
            )

        trace = result["reasoning_trace"]
        assert len(trace) == 1
        assert trace[0]["tool_name"] == "list_low_stock"
        assert trace[0]["result_status"] == "error"
        assert "stock feed down" in trace[0]["result_summary"]


class TestBlockedExecuteInLoop:
    @pytest.mark.asyncio
    async def test_execute_tool_not_invoked_even_if_in_plan(self):
        called = {"patch": False}

        async def patch_menu_price(**kwargs):
            called["patch"] = True
            return {"ok": True}

        async def list_low_stock(store_id: str = ""):
            return {"ok": True, "items": []}

        tools = {
            "list_low_stock": list_low_stock,
            "patch_menu_price": patch_menu_price,
        }
        # patch not on allowlist after policy filter
        req = AgentRunRequest(
            agent_name="inventory_reorder",
            trigger_type="manual",
            allowed_tools=["list_low_stock", "patch_menu_price"],
        )
        pe = PolicyEngine()
        req.allowed_tools = pe.filter_allowlist(req.allowed_tools)
        out = await run_scripted_tool_loop(
            req,
            [
                {"tool": "list_low_stock", "args": {}},
                {"tool": "patch_menu_price", "args": {"id": "x", "price": 1}},
            ],
            tools,
            policy=pe,
        )
        assert called["patch"] is False
        assert "patch_menu_price" not in out["tools_used"]


class TestOpsPreferLlm:
    def test_prefer_false_without_key(self, monkeypatch):
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("OPS_PREFER_LLM", raising=False)
        assert ops_prefer_llm() is False

    def test_prefer_false_when_flag_off(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "x")
        monkeypatch.setenv("OPS_PREFER_LLM", "false")
        assert ops_prefer_llm() is False


class TestProposalExtraction:
    def test_extract_nested_proposals(self):
        props = extract_proposals_from_tool_results([
            {"tool": "x", "result": {"proposal": {
                "type": "DRAFT_PURCHASE_ORDER",
                "store_id": "s",
                "summary": "s",
                "rationale": "r",
            }}},
        ])
        assert len(props) == 1
        assert props[0]["type"] == "DRAFT_PURCHASE_ORDER"


class TestRunOpsAgentWiring:
    @pytest.mark.asyncio
    async def test_run_ops_agent_fallback_path(self):
        async def fb():
            return {"status": "ok", "pos_drafted": 0, "summary": "nothing low"}

        out = await run_ops_agent(
            "inventory_reorder",
            "manual",
            fb,
            prefer_llm=False,
        )
        assert out.get("status") == "ok"
        assert out["_runtime"]["used_fallback"] is True


@pytest.mark.asyncio
async def test_compare_store_performance_has_store_and_fleet(monkeypatch):
    from masova_agent.tools import ops_tools

    async def fake_metrics(store_id=""):
        return {"ok": True, "active": 3 if store_id == "s1" else 1}

    async def fake_stores():
        return {"ok": True, "stores": [{"id": "s1"}, {"id": "s2"}]}

    monkeypatch.setattr(ops_tools, "read_order_metrics", fake_metrics)
    monkeypatch.setattr(ops_tools, "read_kitchen_metrics", fake_metrics)
    monkeypatch.setattr(ops_tools, "list_low_stock", fake_metrics)
    monkeypatch.setattr(ops_tools, "list_stores", fake_stores)
    out = await ops_tools.compare_store_performance("s1")
    assert "store" in out and "fleet" in out
