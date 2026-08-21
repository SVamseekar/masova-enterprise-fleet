"""
Ops multi-step LLM tool loop for agents 2–8.

Uses Google GenAI function calling (same provider stack as chat/ADK).
Short-lived ops sessions: no long-lived ADK session required.

If the model is unavailable or fails, callers rely on AgentRuntime fallback.
Never live-calls in unit tests — inject llm_client or use mock_tool_loop.
"""

from __future__ import annotations

import inspect
import json
import logging
import os
from typing import Any, Awaitable, Callable, Optional

from .models import AgentRunRequest
from .policy import PolicyEngine

logger = logging.getLogger(__name__)

ToolFn = Callable[..., Awaitable[dict[str, Any]] | dict[str, Any]]


def llm_api_key() -> str:
    return (os.getenv("LLM_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()


def ops_model_name() -> str:
    return (
        os.getenv("OPS_LLM_MODEL")
        or os.getenv("LLM_MODEL")
        or os.getenv("GOOGLE_MODEL")
        or "gemini-2.5-flash"
    )


def ops_prefer_llm() -> bool:
    """True when ops should try LLM first (key present unless OPS_PREFER_LLM=false)."""
    flag = (os.getenv("OPS_PREFER_LLM") or "").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return False
    if flag in ("1", "true", "yes", "on"):
        return bool(llm_api_key())
    return bool(llm_api_key())


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


def extract_proposals_from_tool_results(
    tool_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    proposals: list[dict[str, Any]] = []
    for tr in tool_results:
        body = tr.get("result") if isinstance(tr, dict) else None
        if not isinstance(body, dict):
            continue
        if isinstance(body.get("proposal"), dict):
            proposals.append(body["proposal"])
        for p in body.get("proposals") or []:
            if isinstance(p, dict):
                proposals.append(p)
    return proposals


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
    max_calls = request.max_tool_calls or _default_max_tool_calls()

    for step in plan[:max_calls]:
        name = step.get("tool") or step.get("name")
        args = step.get("args") or step.get("arguments") or {}
        if not name:
            continue
        if name not in allowed or not policy.is_allowed(name, allowed):
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
        result = await invoke_tool(fn, args if isinstance(args, dict) else {})
        tools_used.append(name)
        tool_results.append({"tool": name, "result": result})

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
        "tool_results": tool_results,
        "proposals": proposals,
        "used_llm": False,
        "scripted": True,
    }


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
    key = api_key if api_key is not None else llm_api_key()
    if not key:
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

    client = genai.Client(api_key=key)
    model_id = model or ops_model_name()
    max_calls = request.max_tool_calls or _default_max_tool_calls()

    context_pack = {
        "goal": request.goal,
        "store_id": request.store_id,
        "agent": request.agent_name,
        "trigger": request.trigger_type,
        "context": request.context,
    }
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

    contents: list[Any] = [
        genai_types.Content(
            role="user",
            parts=[genai_types.Part(text=user_text)],
        )
    ]

    tools_used: list[str] = []
    tool_results: list[dict[str, Any]] = []
    final_text = ""
    calls = 0

    config = genai_types.GenerateContentConfig(
        system_instruction=system,
        tools=[genai_types.Tool(function_declarations=decls)],
        temperature=0.2,
    )

    while calls < max_calls:
        response = client.models.generate_content(
            model=model_id,
            contents=contents,
            config=config,
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

        # Execute tools and append responses
        response_parts = []
        for name, args in fn_calls:
            calls += 1
            if calls > max_calls:
                break
            if name not in allowed or not policy.is_allowed(name, allowed):
                result = {"ok": False, "error": "tool_not_allowed"}
            else:
                fn = tools.get(name)
                if fn is None:
                    result = {"ok": False, "error": "unknown_tool"}
                else:
                    result = await invoke_tool(fn, args if isinstance(args, dict) else {})
                    tools_used.append(name)
            tool_results.append({"tool": name, "args": args, "result": result})
            response_parts.append(
                genai_types.Part(
                    function_response=genai_types.FunctionResponse(
                        name=name,
                        response=result if isinstance(result, dict) else {"result": result},
                    )
                )
            )

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
