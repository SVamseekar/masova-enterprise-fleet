"""Manager Gemini Chat — text + Gemini voice in the Grok-bot console.

Not a customer agent. Auth is the manager API key (chat:manager).
"""

from __future__ import annotations

import base64
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

MANAGER_INSTRUCTION = """You are MaSoVa AI, the operations assistant for a restaurant regional manager.

You help one manager run a fleet of specialist agents against live store data.
You never execute prices, purchase orders, refunds, or campaigns — you only read,
compute, and propose. The manager approves in this same chat.

When the manager asks about stock, run inventory for the focus store.
When they ask about prices or kitchen load, run the pricing signal.
Use tools for every number. Do not invent quantities, prices, or order counts.
Keep replies short and operational. If you drafted something, say it needs their OK.
"""

MANAGER_TOOLS = [
    "list_stores",
    "list_low_stock",
    "count_active_orders",
    "count_recent_orders",
    "get_forecast_snippet",
    "get_top_items",
    "compute_pricing_signal",
    "get_order_context",
    "read_kitchen_metrics",
    "read_order_metrics",
    "notify_managers",
    "run_inventory_reorder",
    "run_dynamic_pricing",
    "run_demand_forecast",
    "run_churn_prevention",
    "run_shift_optimisation",
    "run_kitchen_coach",
    "run_review_response",
    "list_pending_proposals",
    "approve_proposal",
    "reject_proposal",
    "search_ops_manual",
]


async def _call_specialist(fn, store_id: str = "") -> dict[str, Any]:
    """Call specialist run_*; pass store_id when the signature accepts it (Lane A)."""
    import inspect

    params = inspect.signature(fn).parameters
    if "store_id" in params:
        return await fn(store_id=store_id or None)
    return await fn()


async def run_inventory_reorder_tool(store_id: str = "") -> dict[str, Any]:
    from .inventory_reorder_agent import run_inventory_reorder

    return await _call_specialist(run_inventory_reorder, store_id)


async def run_dynamic_pricing_tool(store_id: str = "") -> dict[str, Any]:
    from .dynamic_pricing_agent import run_dynamic_pricing

    return await _call_specialist(run_dynamic_pricing, store_id)


async def run_demand_forecast_tool(store_id: str = "") -> dict[str, Any]:
    from .demand_forecasting_agent import run_demand_forecast

    return await _call_specialist(run_demand_forecast, store_id)


async def run_churn_prevention_tool(store_id: str = "") -> dict[str, Any]:
    from .churn_prevention_agent import run_churn_prevention

    return await _call_specialist(run_churn_prevention, store_id)


async def run_shift_optimisation_tool(store_id: str = "") -> dict[str, Any]:
    from .shift_optimisation_agent import run_shift_optimisation

    return await _call_specialist(run_shift_optimisation, store_id)


async def run_kitchen_coach_tool(store_id: str = "") -> dict[str, Any]:
    from .kitchen_coach_agent import run_kitchen_coach

    return await _call_specialist(run_kitchen_coach, store_id)


async def _latest_low_rating_review(store_id: str) -> Optional[dict[str, Any]]:
    """Load newest rating≤3 review for the store from ops/demo if available."""
    try:
        import httpx
        from ..tools.ops_http import agent_token, get_json, unwrap_list

        if not agent_token():
            return None
        params = {"storeId": store_id} if store_id else {}
        async with httpx.AsyncClient(timeout=15.0) as client:
            status, body = await get_json(client, "/api/reviews", params=params)
            if status != 200:
                return None
            for row in unwrap_list(body):
                rating = int(row.get("rating") or 5)
                if rating <= 3:
                    return {
                        "reviewId": row.get("id") or row.get("reviewId"),
                        "rating": rating,
                        "text": row.get("text") or row.get("comment") or "",
                        "storeId": row.get("storeId") or store_id,
                        "orderId": row.get("orderId"),
                    }
    except Exception as e:
        logger.warning("low-rating review lookup failed: %s", e)
    return None


async def run_review_response_tool(store_id: str = "") -> dict[str, Any]:
    from .review_response_agent import draft_review_response

    review = await _latest_low_rating_review(store_id or "")
    if not review:
        return {"ok": False, "error": "no_low_rating_review", "store_id": store_id or ""}
    return await draft_review_response(review)


# Re-export proposal tools for chat + tests (implementation in tools/proposal_tools.py)
async def list_pending_proposals(store_id: str = "") -> dict[str, Any]:
    from ..tools.proposal_tools import list_pending_proposals as _list

    return await _list(store_id=store_id)


async def approve_proposal(proposal_id: str, note: str = "") -> dict[str, Any]:
    from ..tools.proposal_tools import approve_proposal as _approve

    return await _approve(proposal_id, note=note)


async def reject_proposal(proposal_id: str, note: str = "") -> dict[str, Any]:
    from ..tools.proposal_tools import reject_proposal as _reject

    return await _reject(proposal_id, note=note)


_RUN_TOOL_SCHEMA = {
    "type": "object",
    "properties": {"store_id": {"type": "string"}},
}


def _manager_llm_runner():
    from ..runtime.ops_llm import make_ops_llm_runner
    from ..tools.ops_tools import OPS_TOOL_FUNCTIONS, OPS_TOOL_SCHEMAS
    from ..knowledge.rag import search_ops_manual

    run_fns = {
        "run_inventory_reorder": run_inventory_reorder_tool,
        "run_dynamic_pricing": run_dynamic_pricing_tool,
        "run_demand_forecast": run_demand_forecast_tool,
        "run_churn_prevention": run_churn_prevention_tool,
        "run_shift_optimisation": run_shift_optimisation_tool,
        "run_kitchen_coach": run_kitchen_coach_tool,
        "run_review_response": run_review_response_tool,
        "list_pending_proposals": list_pending_proposals,
        "approve_proposal": approve_proposal,
        "reject_proposal": reject_proposal,
    }
    run_schemas = {
        "run_inventory_reorder": {
            "description": "Run the inventory specialist: low stock → draft PO for manager approval.",
            "parameters": _RUN_TOOL_SCHEMA,
        },
        "run_dynamic_pricing": {
            "description": "Run the pricing specialist: suggest capped price changes, never PATCH the menu.",
            "parameters": _RUN_TOOL_SCHEMA,
        },
        "run_demand_forecast": {
            "description": "Run demand forecasting for the focus store (writes forecast proposal only).",
            "parameters": _RUN_TOOL_SCHEMA,
        },
        "run_churn_prevention": {
            "description": "Run churn prevention: draft win-back campaign for manager approval.",
            "parameters": _RUN_TOOL_SCHEMA,
        },
        "run_shift_optimisation": {
            "description": "Run shift optimisation: draft roster for manager approval.",
            "parameters": _RUN_TOOL_SCHEMA,
        },
        "run_kitchen_coach": {
            "description": "Run kitchen coach: draft coaching brief from live kitchen metrics.",
            "parameters": _RUN_TOOL_SCHEMA,
        },
        "run_review_response": {
            "description": "Draft a reply for the latest low-rating review at the store (manager approval).",
            "parameters": _RUN_TOOL_SCHEMA,
        },
        "list_pending_proposals": {
            "description": "List PENDING ActionProposals for a store (HITL queue).",
            "parameters": {
                "type": "object",
                "properties": {"store_id": {"type": "string"}},
            },
        },
        "approve_proposal": {
            "description": "Approve a PENDING proposal (same path as HTTP resolve). Never executes commerce writes beyond apply hooks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "proposal_id": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["proposal_id"],
            },
        },
        "reject_proposal": {
            "description": "Reject a PENDING proposal (same path as HTTP resolve).",
            "parameters": {
                "type": "object",
                "properties": {
                    "proposal_id": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["proposal_id"],
            },
        },
    }
    extra_fns = {
        **{n: OPS_TOOL_FUNCTIONS[n] for n in MANAGER_TOOLS if n in OPS_TOOL_FUNCTIONS},
        **run_fns,
        "search_ops_manual": search_ops_manual,
    }
    extra_schemas = {
        **{n: OPS_TOOL_SCHEMAS[n] for n in MANAGER_TOOLS if n in OPS_TOOL_SCHEMAS},
        **run_schemas,
        "search_ops_manual": {
            "description": (
                "Search restaurant ops manuals (HACCP, equipment, labour, supplier SLAs). "
                "SOP text only — never a substitute for live stock or order numbers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "category": {"type": "string"},
                },
                "required": ["query"],
            },
        },
    }
    return make_ops_llm_runner(
        instruction=MANAGER_INSTRUCTION,
        tool_names=list(MANAGER_TOOLS),
        tool_functions=extra_fns,
        tool_schemas=extra_schemas,
    )


async def transcribe_manager_audio(audio_bytes: bytes, mime_type: str = "audio/webm") -> str:
    """Gemini audio understanding → transcript. Raises if the model is unavailable."""
    from ..runtime.ops_llm import llm_api_key, ops_model_name
    from google import genai
    from google.genai import types as genai_types

    key = llm_api_key()
    if not key:
        raise RuntimeError("LLM_API_KEY_not_configured")
    client = genai.Client(api_key=key)
    response = client.models.generate_content(
        model=ops_model_name(),
        contents=[
            genai_types.Content(
                role="user",
                parts=[
                    genai_types.Part.from_bytes(data=audio_bytes, mime_type=mime_type or "audio/webm"),
                    genai_types.Part.from_text(
                        text="Transcribe this manager's spoken request in English. Return only the transcript."
                    ),
                ],
            )
        ],
    )
    text = (getattr(response, "text", None) or "").strip()
    if not text:
        raise RuntimeError("empty_transcript")
    return text


async def run_manager_chat(
    message: str,
    *,
    store_id: Optional[str] = None,
    session_id: str = "",
    audio_base64: Optional[str] = None,
    mime_type: str = "audio/webm",
) -> dict[str, Any]:
    """Public entry for POST /agent/manager/chat."""
    from ..runtime.wrap import run_ops_agent
    from ..runtime.ops_llm import ops_prefer_llm
    from ..services.demo_backend import demo_focus_store_id, demo_mode
    from ..runtime.guardrails import screen_input, screen_output

    transcript = ""
    if audio_base64 and not (message or "").strip():
        raw = base64.b64decode(audio_base64)
        transcript = await transcribe_manager_audio(raw, mime_type=mime_type)
        message = transcript
    message = (message or "").strip()
    if not message:
        return {"reply": "Say or type what you need — inventory, pricing, or a store check.", "sessionId": session_id}

    if not store_id and demo_mode():
        store_id = demo_focus_store_id()

    screened = screen_input(message)
    if not screened.allowed:
        return {
            "reply": "I can't run that request.",
            "sessionId": session_id,
            "transcript": transcript,
            "blocked": True,
        }

    async def _fallback():
        return {
            "status": "ok",
            "reply": (
                "I couldn't reach Gemini just now. Use the chips under the composer "
                "(Run inventory, Pricing signal, Store proof) — those still hit the live agents."
            ),
            "summary": "manager_chat_fallback",
        }

    result = await run_ops_agent(
        "manager_chat",
        "chat",
        _fallback,
        store_id=store_id,
        goal=screened.redacted_text[:800],
        context={"store_id": store_id, "session_id": session_id, "message": screened.redacted_text},
        llm_runner=_manager_llm_runner() if ops_prefer_llm() else None,
        prefer_llm=ops_prefer_llm(),
        allowed_tools=list(MANAGER_TOOLS),
    )

    reply = str(result.get("reply") or result.get("summary") or "").strip()
    if not reply:
        reply = "Done. Check the thread for any proposal that needs your OK."
    out_screen = screen_output(reply)
    if not out_screen.allowed:
        reply = "I can't show that reply."

    runtime = result.get("_runtime") or {}
    return {
        "reply": reply,
        "sessionId": session_id,
        "transcript": transcript,
        "storeId": store_id,
        "run_id": runtime.get("run_id") or result.get("run_id"),
        "proposals": runtime.get("proposals") or result.get("proposals") or [],
        "tools_used": runtime.get("tools_used") or result.get("tools_used") or [],
        "used_fallback": bool(runtime.get("used_fallback")),
    }
