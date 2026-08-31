"""
Ops multi-step LLM tool loop for agents 2–8.

Uses Google GenAI function calling (same provider stack as chat/ADK).
Short-lived ops sessions: no long-lived ADK session required.

If the model is unavailable or fails, callers rely on AgentRuntime fallback.
Never live-calls in unit tests — inject llm_client or use mock_tool_loop.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import time
from typing import Any, Awaitable, Callable, Optional

from .models import AgentRunRequest, RiskTier, _utc_now_iso
from .ops_contract import LOW_STOCK_TOOLS, hydrate_propose_args, skip_incomplete_propose
from .policy import PolicyEngine

logger = logging.getLogger(__name__)

ToolFn = Callable[..., Awaitable[dict[str, Any]] | dict[str, Any]]


def llm_api_key() -> str:
    return (os.getenv("LLM_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()


def use_vertexai() -> bool:
    return (os.getenv("GOOGLE_GENAI_USE_VERTEXAI") or "").strip().lower() in ("1", "true", "yes", "on")


def llm_available() -> bool:
    """True when the GenAI client can be constructed: an API key, or Vertex AI
    (auth via ADC/service account — no key needed)."""
    return bool(llm_api_key()) or use_vertexai()


def make_genai_client(api_key: str | None = None):
    """Vertex AI (ADC/service-account auth, no key) when GOOGLE_GENAI_USE_VERTEXAI
    is set; otherwise API-key auth. Callers should check llm_available() first."""
    from google import genai

    if use_vertexai():
        project = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT_ID")
        location = os.getenv("GOOGLE_CLOUD_LOCATION") or os.getenv("GCP_LOCATION") or "us-central1"
        return genai.Client(vertexai=True, project=project, location=location)
    key = api_key if api_key is not None else llm_api_key()
    if not key:
        raise RuntimeError("LLM_API_KEY_not_configured")
    return genai.Client(api_key=key)


def ops_model_name() -> str:
    return (
        os.getenv("OPS_LLM_MODEL")
        or os.getenv("LLM_MODEL")
        or os.getenv("GOOGLE_MODEL")
        or "gemini-3.5-flash"
    )


def ops_prefer_llm() -> bool:
    """True when ops should try LLM first (key present unless OPS_PREFER_LLM=false)."""
    flag = (os.getenv("OPS_PREFER_LLM") or "").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return False
    if flag in ("1", "true", "yes", "on"):
        return llm_available()
    return llm_available()


def _context_char_limit() -> int:
    try:
        return max(1000, int(os.getenv("OPS_CONTEXT_CHARS", "8000")))
    except ValueError:
        return 8000


def _default_max_tool_calls() -> int:
    try:
        return max(1, min(50, int(os.getenv("OPS_MAX_TOOL_CALLS", "12"))))
    except ValueError:
        return 12


def _json_safe(obj: Any, limit: int | None = None) -> str:
    if limit is None:
        limit = _context_char_limit()
    try:
        s = json.dumps(obj, default=str)
    except Exception:
        s = str(obj)
    if len(s) > limit:
        return s[:limit] + "…"
    return s


def _summarize_result(result: Any) -> str:
    """Short manager-facing line — never dump raw tool JSON into the thread."""
    if not isinstance(result, dict):
        return str(result)[:160]
    if result.get("error"):
        return str(result["error"])[:160]
    if result.get("skipped") or result.get("duplicate"):
        return str(result.get("reason") or "Already drafted this window")
    if "customers" in result:
        n = result.get("count")
        if n is None:
            n = len(result.get("customers") or [])
        return f"{n} guest(s) in the churn segment"
    if "staff" in result and isinstance(result.get("staff"), list):
        return f"{len(result['staff'])} staff available"
    items = result.get("items")
    if isinstance(items, list) and items and isinstance(items[0], dict):
        names = [
            str(i.get("name") or i.get("itemName") or i.get("item_name") or "")
            for i in items[:3]
        ]
        names = [n for n in names if n]
        qty = items[0].get("quantity") or items[0].get("reorder_quantity") or items[0].get("current_stock") or items[0].get("currentStock")
        if "current_stock" in items[0] or "currentStock" in items[0]:
            bit = f"{len(items)} low-stock"
            if names:
                bit += ": " + ", ".join(names)
            if qty is not None:
                bit += f" ({qty})"
            return bit
        if names:
            extra = f" {qty}" if qty is not None else ""
            return ", ".join(names) + extra
    if result.get("ticket_count") is not None:
        return (
            f"{result.get('ticket_count')} tickets · "
            f"{result.get('avg_prep_minutes')} min avg · "
            f"{result.get('slow_tickets')} slow"
        )
    if result.get("forecast") is not None:
        return f"WMA forecast {result.get('forecast')}"
    if result.get("series") and isinstance(result.get("series"), list):
        return f"{len(result['series'])} days of order history"
    if result.get("proposal") and isinstance(result["proposal"], dict):
        return str(result["proposal"].get("summary") or "Draft ready")[:160]
    if result.get("sent") is not None:
        return f"Notified {result.get('sent')} manager(s)"
    if result.get("ok") is True:
        return "Done"
    try:
        return json.dumps(result, default=str)[:160]
    except Exception:
        return str(result)[:160]


def hydrate_tool_args(
    tool_name: str,
    args: dict[str, Any],
    prior_results: list[dict[str, Any]],
) -> dict[str, Any]:
    return hydrate_propose_args(tool_name, args, prior_results)


def pin_tool_args(fn: ToolFn, args: dict[str, Any], request_store_id: Optional[str]) -> dict[str, Any]:
    """Force tool store_id to the run's store so the model cannot walk the fleet."""
    pinned = dict(args or {})
    if not request_store_id:
        return pinned
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return pinned
    if "store_id" in params:
        pinned["store_id"] = request_store_id
    return pinned


async def invoke_tool(fn: ToolFn, args: dict[str, Any]) -> dict[str, Any]:
    """Call tool with only parameters it accepts."""
    try:
        sig = inspect.signature(fn)
        accepted = {
            k: v for k, v in (args or {}).items()
            if k in sig.parameters
        }
        # Fill missing required-ish with defaults when possible
        result = fn(**accepted)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, dict):
            return {"ok": True, "result": result}
        return result
    except TypeError as e:
        return {"ok": False, "error": f"tool_args:{e}"}
    except Exception as e:
        logger.warning("Tool %s failed: %s", getattr(fn, "__name__", fn), e)
        return {"ok": False, "error": f"{type(e).__name__}:{e}"}


def _upsert_running_trace(
    request: AgentRunRequest,
    tools_used: list[str],
    trace: list[dict[str, Any]],
) -> None:
    if not request.run_id:
        return
    from . import run_store
    run_store.upsert_run({
        "run_id": request.run_id,
        "agent": request.agent_name,
        "status": "running",
        "store_id": request.store_id,
        "tools_used": list(tools_used),
        "reasoning_trace": list(trace),
    })


def extract_proposals_from_tool_results(
    tool_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    proposals: list[dict[str, Any]] = []
    for index, tr in enumerate(tool_results):
        body = tr.get("result") if isinstance(tr, dict) else None
        if not isinstance(body, dict):
            continue
        if isinstance(body.get("proposal"), dict):
            proposals.append(
                _with_tool_evidence(body["proposal"], tool_results[:index])
            )
        for p in body.get("proposals") or []:
            if isinstance(p, dict):
                proposals.append(_with_tool_evidence(p, tool_results[:index]))
    return proposals


def _with_tool_evidence(
    proposal: dict[str, Any],
    prior_tool_results: list[dict[str, Any]],
) -> dict[str, Any]:
    out = dict(proposal)
    if out.get("type") != "DRAFT_PURCHASE_ORDER":
        return out

    evidence = _inventory_evidence_for_proposal(out, prior_tool_results)
    if evidence:
        out["evidence"] = evidence
    else:
        out.pop("evidence", None)
    return out


def _inventory_evidence_for_proposal(
    proposal: dict[str, Any],
    prior_tool_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    payload = proposal.get("payload") or {}
    item_ids = set()
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        row_id = item.get("inventoryItemId") or item.get("inventory_item_id") or item.get("id")
        if row_id:
            item_ids.add(str(row_id))

    evidence: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for tr in prior_tool_results:
        tool = str(tr.get("tool") or "")
        if tool not in LOW_STOCK_TOOLS:
            continue
        result = tr.get("result")
        if not isinstance(result, dict):
            continue
        for row in result.get("items") or []:
            if not isinstance(row, dict):
                continue
            row_id = row.get("id") or row.get("inventoryItemId") or row.get("inventory_item_id")
            if not row_id:
                continue
            row_id = str(row_id)
            if item_ids and row_id not in item_ids:
                continue
            value = row.get("currentStock", row.get("current_stock"))
            if value is None:
                continue
            key = (tool, row_id, "currentStock")
            if key in seen:
                continue
            seen.add(key)
            evidence.append({
                "tool": tool,
                "row_id": row_id,
                "field": "currentStock",
                "value": value,
            })
    return evidence


async def run_scripted_tool_loop(
    request: AgentRunRequest,
    plan: list[dict[str, Any]],
    tools: dict[str, ToolFn],
    policy: PolicyEngine | None = None,
) -> dict[str, Any]:
    """
    Deterministic multi-step executor for tests / offline golden paths.

    plan: [{"tool": "list_low_stock", "args": {...}}, ...]
    """
    policy = policy or PolicyEngine()
    allowed = set(request.allowed_tools or [])
    tools_used: list[str] = []
    tool_results: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    max_calls = request.max_tool_calls or _default_max_tool_calls()

    for step in plan[:max_calls]:
        name = step.get("tool") or step.get("name")
        args = step.get("args") or step.get("arguments") or {}
        if not name:
            continue
        if name not in allowed:
            tool_results.append({
                "tool": name,
                "result": {"ok": False, "error": "tool_not_allowed"},
            })
            continue
        tier = policy.tier_for(name)
        if tier == RiskTier.EXECUTE:
            tool_results.append({
                "tool": name,
                "result": {"ok": False, "error": "tool_not_allowed"},
            })
            continue
        if tier is not None and not policy.is_allowed(name, allowed):
            tool_results.append({
                "tool": name,
                "result": {"ok": False, "error": "tool_not_allowed"},
            })
            continue
        fn = tools.get(name)
        if fn is None:
            tool_results.append({
                "tool": name,
                "result": {"ok": False, "error": "unknown_tool"},
            })
            continue
        started = time.perf_counter()
        try:
            pinned = pin_tool_args(fn, args if isinstance(args, dict) else {}, request.store_id)
            pinned = hydrate_tool_args(name, pinned, tool_results)
            skipped = skip_incomplete_propose(name, pinned, tool_results)
            result = skipped if skipped is not None else await invoke_tool(fn, pinned)
        except Exception as e:
            result = {"ok": False, "error": f"{type(e).__name__}:{e}"}
        duration_ms = (time.perf_counter() - started) * 1000
        tools_used.append(name)
        tool_results.append({"tool": name, "args": args, "result": result})
        trace.append({
            "index": len(trace),
            "tool_name": name,
            "args": args,
            "result_status": "error" if isinstance(result, dict) and result.get("error") else "ok",
            "result_summary": _summarize_result(result),
            "duration_ms": duration_ms,
            "at": _utc_now_iso(),
        })
        _upsert_running_trace(request, tools_used, trace)

    proposals = extract_proposals_from_tool_results(tool_results)
    summary = str(
        request.context.get("summary_hint")
        or f"{request.agent_name} tool loop: {len(tools_used)} calls, {len(proposals)} proposals"
    )
    rationale = ""
    for p in proposals:
        if p.get("rationale"):
            rationale = str(p["rationale"])
            break

    return {
        "status": "ok",
        "summary": summary,
        "rationale": rationale,
        "tools_used": tools_used,
        "reasoning_trace": trace,
        "tool_results": tool_results,
        "proposals": proposals,
        "used_llm": False,
        "scripted": True,
    }


def build_genai_loop_prompts(
    request: AgentRunRequest,
    *,
    instruction: str,
    max_calls: int,
    context_pack: dict[str, Any],
) -> tuple[str, str]:
    """System + user text for the GenAI tool loop.

    Manager chat is a briefing, not a proposal-summary dump.
    """
    chat = request.agent_name == "manager_chat"
    if chat:
        system = (
            f"{instruction.strip()}\n\n"
            "Rules:\n"
            "- Use tools for ALL numbers (stock, forecasts, order counts, prices).\n"
            "- Never invent inventory quantities, forecasts, or menu prices.\n"
            "- Only PROPOSE drafts; never claim you executed final writes.\n"
            "- Reply in spoken-manager English. No # headings. No UUID as the store name.\n"
            f"- Max tool rounds: {max_calls}.\n"
        )
        goal = (request.goal or "").strip()
        user_text = (
            f"The manager asked:\n{goal}\n\n"
            f"Focus store_id: {request.store_id or ''}\n"
            "Call the fewest tools that ground the answer, then reply as a brief "
            "to a person in the store — not a report, not a JSON dump."
        )
        return system, user_text

    system = (
        f"{instruction.strip()}\n\n"
        "Rules:\n"
        "- Use tools for ALL numbers (stock, forecasts, order counts, prices).\n"
        "- Never invent inventory quantities, forecasts, or menu prices.\n"
        "- Only PROPOSE drafts and notifications; never claim you executed final writes.\n"
        "- Include clear rationale when proposing actions.\n"
        f"- Max tool rounds: {max_calls}.\n"
    )
    user_text = (
        f"Run the ops agent task.\nContext pack:\n{_json_safe(context_pack)}\n"
        "Call tools as needed, then finish with a short summary of proposals."
    )
    return system, user_text


async def run_genai_tool_loop(
    request: AgentRunRequest,
    *,
    instruction: str,
    tools: dict[str, ToolFn],
    tool_schemas: dict[str, dict[str, Any]],
    policy: PolicyEngine | None = None,
    model: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """
    Multi-step function-calling loop via google.genai Client.

    Raises on missing key / import / empty model responses so AgentRuntime
    can fall back to rule path.
    """
    if api_key is None and not llm_available():
        raise RuntimeError("LLM_API_KEY_not_configured")

    policy = policy or PolicyEngine()
    allowed = [t for t in (request.allowed_tools or []) if policy.is_allowed(t, request.allowed_tools)]
    if not allowed:
        raise RuntimeError("no_allowed_tools")

    from google import genai
    from google.genai import types as genai_types

    decls = []
    for name in allowed:
        schema = tool_schemas.get(name) or {
            "description": f"Ops tool {name}",
            "parameters": {"type": "object", "properties": {}},
        }
        params = schema.get("parameters") or {"type": "object", "properties": {}}
        decls.append(
            genai_types.FunctionDeclaration(
                name=name,
                description=schema.get("description") or name,
                parameters=params,
            )
        )

    client = make_genai_client(api_key)
    model_id = model or ops_model_name()
    max_calls = request.max_tool_calls or _default_max_tool_calls()

    context_pack = {
        "goal": request.goal,
        "store_id": request.store_id,
        "agent": request.agent_name,
        "trigger": request.trigger_type,
        "context": request.context,
    }
    system, user_text = build_genai_loop_prompts(
        request, instruction=instruction, max_calls=max_calls, context_pack=context_pack
    )

    contents: list[Any] = []
    history = request.context.get("history") if isinstance(request.context, dict) else None
    if isinstance(history, list):
        for turn in history:
            if not isinstance(turn, dict):
                continue
            role = str(turn.get("role") or "user")
            if role not in ("user", "model"):
                role = "user" if role in ("human", "manager") else "model"
            text = str(turn.get("text") or turn.get("content") or "")
            if not text:
                continue
            contents.append(
                genai_types.Content(
                    role=role,
                    parts=[genai_types.Part(text=text)],
                )
            )
    contents.append(
        genai_types.Content(
            role="user",
            parts=[genai_types.Part(text=user_text)],
        )
    )

    tools_used: list[str] = []
    tool_results: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    final_text = ""
    calls = 0
    # De-dup cache for tools whose result only depends on their args (e.g.
    # search_ops_manual) — Gemini sometimes re-issues the same lookup with
    # minor rephrasing across turns; skip the repeat network round-trip.
    DEDUP_TOOLS = {
        "search_ops_manual",
        "read_churn_segment",
        "list_low_stock",
        "read_inventory_levels",
        "read_kitchen_metrics",
        "read_order_metrics",
        "read_staff_slots",
        "get_top_items",
        "get_slow_items",
        "list_stores",
    }
    dedup_cache: dict[tuple[str, str], dict[str, Any]] = {}

    config = genai_types.GenerateContentConfig(
        system_instruction=system,
        tools=[genai_types.Tool(function_declarations=decls)],
        temperature=0.35 if request.agent_name == "manager_chat" else 0.2,
    )

    try:
        timeout_sec = max(1, int(os.getenv("OPS_LLM_TIMEOUT_SEC", "45")))
    except ValueError:
        timeout_sec = 45

    while calls < max_calls:
        response = await asyncio.wait_for(
            asyncio.to_thread(
                client.models.generate_content,
                model=model_id,
                contents=contents,
                config=config,
            ),
            timeout=timeout_sec,
        )

        # Parse function calls
        fn_calls = []
        text_parts: list[str] = []
        candidate = None
        try:
            candidate = response.candidates[0] if response.candidates else None
        except Exception:
            candidate = None

        if candidate and candidate.content and candidate.content.parts:
            for part in candidate.content.parts:
                fc = getattr(part, "function_call", None)
                if fc and getattr(fc, "name", None):
                    args = dict(fc.args) if getattr(fc, "args", None) else {}
                    fn_calls.append((fc.name, args))
                t = getattr(part, "text", None)
                if t:
                    text_parts.append(t)

        if not fn_calls:
            final_text = "\n".join(text_parts).strip()
            break

        # Append model turn
        if candidate and candidate.content:
            contents.append(candidate.content)

        # Execute tools for this turn concurrently (independent calls — each
        # has its own pinned args and result slot), then append responses in
        # the original, deterministic order.
        runnable = []
        for name, args in fn_calls:
            calls += 1
            if calls > max_calls:
                break
            runnable.append((name, args))

        async def _run_one(name: str, args: Any) -> dict[str, Any]:
            started = time.perf_counter()
            dedup_key = (name, _json_safe(args)) if name in DEDUP_TOOLS else None
            if dedup_key is not None and dedup_key in dedup_cache:
                result: dict[str, Any] = dedup_cache[dedup_key]
            elif name not in allowed or not policy.is_allowed(name, allowed):
                result = {"ok": False, "error": "tool_not_allowed"}
            else:
                fn = tools.get(name)
                if fn is None:
                    result = {"ok": False, "error": "unknown_tool"}
                else:
                    try:
                        pinned = pin_tool_args(
                            fn, args if isinstance(args, dict) else {}, request.store_id
                        )
                        pinned = hydrate_tool_args(name, pinned, tool_results)
                        skipped = skip_incomplete_propose(name, pinned, tool_results)
                        result = skipped if skipped is not None else await invoke_tool(fn, pinned)
                    except Exception as e:
                        result = {"ok": False, "error": f"{type(e).__name__}:{e}"}
                if dedup_key is not None:
                    dedup_cache[dedup_key] = result
            duration_ms = (time.perf_counter() - started) * 1000
            return {"name": name, "args": args, "result": result, "duration_ms": duration_ms}

        outcomes = await asyncio.gather(*[_run_one(name, args) for name, args in runnable])

        response_parts = []
        for outcome in outcomes:
            name, args, result = outcome["name"], outcome["args"], outcome["result"]
            if not (isinstance(result, dict) and result.get("error") == "tool_not_allowed"):
                tools_used.append(name)
            tool_results.append({"tool": name, "args": args, "result": result})
            trace.append({
                "index": len(trace),
                "tool_name": name,
                "args": args,
                "result_status": "error" if isinstance(result, dict) and result.get("error") else "ok",
                "result_summary": _summarize_result(result),
                "duration_ms": outcome["duration_ms"],
                "at": _utc_now_iso(),
            })
            response_parts.append(
                genai_types.Part(
                    function_response=genai_types.FunctionResponse(
                        name=name,
                        response=result if isinstance(result, dict) else {"result": result},
                    )
                )
            )
            _upsert_running_trace(request, tools_used, trace)

        contents.append(
            genai_types.Content(role="user", parts=response_parts)
        )

    proposals = extract_proposals_from_tool_results(tool_results)
    summary = final_text or (
        f"{request.agent_name}: {len(tools_used)} tool calls, {len(proposals)} proposals"
    )
    rationale = final_text
    for p in proposals:
        if p.get("rationale"):
            rationale = str(p["rationale"])
            break

    # Map common counters for legacy HTTP clients
    output: dict[str, Any] = {
        "status": "ok",
        "summary": summary[:1000],
        "rationale": (rationale or "")[:2000],
        "tools_used": tools_used,
        "reasoning_trace": trace,
        "tool_results": tool_results,
        "proposals": proposals,
        "used_llm": True,
        "model": model_id,
    }
    # Heuristic counters
    for p in proposals:
        t = p.get("type")
        if t == "DRAFT_PURCHASE_ORDER":
            output["pos_drafted"] = output.get("pos_drafted", 0) + 1
        elif t == "SUGGEST_PRICE_ADJUSTMENT":
            output["suggestions_sent"] = output.get("suggestions_sent", 0) + 1
        elif t == "DRAFT_CHURN_CAMPAIGN":
            output["campaigns_drafted"] = output.get("campaigns_drafted", 0) + 1
        elif t == "DRAFT_SHIFT_ROSTER":
            output["shifts_drafted"] = output.get("shifts_drafted", 0) + 1
        elif t == "DRAFT_KITCHEN_BRIEF":
            output["briefs_sent"] = output.get("briefs_sent", 0) + 1
        elif t == "DRAFT_REVIEW_REPLY":
            output["drafts_created"] = output.get("drafts_created", 0) + 1
        elif t == "WRITE_FORECAST":
            output["forecasts_written"] = output.get("forecasts_written", 0) + 1

    return output


def make_ops_llm_runner(
    *,
    instruction: str,
    tool_names: list[str],
    tool_functions: dict[str, ToolFn] | None = None,
    tool_schemas: dict[str, dict[str, Any]] | None = None,
    build_context: Optional[Callable[[AgentRunRequest], dict[str, Any] | Awaitable]] = None,
    pre_gate: Optional[Callable[[AgentRunRequest], dict[str, Any] | Awaitable | None]] = None,
    scripted_plan: Optional[list[dict[str, Any]]] = None,
) -> Callable[[AgentRunRequest], Awaitable[dict[str, Any]]]:
    """
    Build an llm_runner for AgentRunRequest.

    pre_gate: if returns a dict, skip LLM and return that result (e.g. pricing no-signal).
    scripted_plan: if set, run deterministic tool plan instead of live GenAI (tests).
    """
    from ..tools.ops_tools import OPS_TOOL_FUNCTIONS, OPS_TOOL_SCHEMAS

    tools = tool_functions or {
        n: OPS_TOOL_FUNCTIONS[n]
        for n in tool_names
        if n in OPS_TOOL_FUNCTIONS
    }
    schemas = tool_schemas or {
        n: OPS_TOOL_SCHEMAS[n]
        for n in tool_names
        if n in OPS_TOOL_SCHEMAS
    }

    async def _runner(request: AgentRunRequest) -> dict[str, Any]:
        # Ensure allowlist includes declared tools
        if not request.allowed_tools:
            request.allowed_tools = list(tool_names)
        else:
            # Intersection-friendly: keep request allowlist
            pass

        if build_context is not None:
            ctx = build_context(request)
            if inspect.isawaitable(ctx):
                ctx = await ctx
            if isinstance(ctx, dict):
                merged = dict(request.context or {})
                merged.update(ctx)
                request.context = merged

        if pre_gate is not None:
            gate = pre_gate(request)
            if inspect.isawaitable(gate):
                gate = await gate
            if isinstance(gate, dict):
                gate.setdefault("status", "ok")
                gate.setdefault("tools_used", gate.get("tools_used") or [])
                gate.setdefault("proposals", gate.get("proposals") or [])
                gate.setdefault("used_llm", False)
                gate.setdefault("skipped_llm", True)
                return gate

        if scripted_plan is not None:
            return await run_scripted_tool_loop(request, scripted_plan, tools)

        # Optional: context may embed a test plan
        if request.context.get("_scripted_plan"):
            return await run_scripted_tool_loop(
                request, list(request.context["_scripted_plan"]), tools
            )

        return await run_genai_tool_loop(
            request,
            instruction=instruction,
            tools=tools,
            tool_schemas=schemas,
        )

    return _runner
