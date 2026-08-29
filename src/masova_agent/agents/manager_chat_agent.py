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
]


async def run_inventory_reorder_tool(store_id: str = "") -> dict[str, Any]:
    from .inventory_reorder_agent import run_inventory_reorder

    return await run_inventory_reorder(store_id=store_id or None)


async def run_dynamic_pricing_tool(store_id: str = "") -> dict[str, Any]:
    from .dynamic_pricing_agent import run_dynamic_pricing

    return await run_dynamic_pricing(store_id=store_id or None)


def _manager_llm_runner():
    from ..runtime.ops_llm import make_ops_llm_runner
    from ..tools.ops_tools import OPS_TOOL_FUNCTIONS, OPS_TOOL_SCHEMAS

    extra_fns = {
        **{n: OPS_TOOL_FUNCTIONS[n] for n in MANAGER_TOOLS if n in OPS_TOOL_FUNCTIONS},
        "run_inventory_reorder": run_inventory_reorder_tool,
        "run_dynamic_pricing": run_dynamic_pricing_tool,
    }
    extra_schemas = {
        **{n: OPS_TOOL_SCHEMAS[n] for n in MANAGER_TOOLS if n in OPS_TOOL_SCHEMAS},
        "run_inventory_reorder": {
            "description": "Run the inventory specialist: low stock → draft PO for manager approval.",
            "parameters": {
                "type": "object",
                "properties": {"store_id": {"type": "string"}},
            },
        },
        "run_dynamic_pricing": {
            "description": "Run the pricing specialist: suggest capped price changes, never PATCH the menu.",
            "parameters": {
                "type": "object",
                "properties": {"store_id": {"type": "string"}},
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
