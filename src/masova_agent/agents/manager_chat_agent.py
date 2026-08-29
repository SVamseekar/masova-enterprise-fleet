"""Manager Gemini Chat — text + Gemini voice in the Grok-bot console.

Not a customer agent. Auth is the manager API key (chat:manager).
"""

from __future__ import annotations

import base64
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Process-local multi-turn buffer when Redis is down (Cloud Run single instance).
_MANAGER_TURNS: dict[str, list[dict[str, str]]] = {}
_MAX_MANAGER_TURNS = 10


def _history_for_session(session_id: str) -> list[dict[str, str]]:
    sid = (session_id or "").strip() or "_anon"
    return list(_MANAGER_TURNS.get(sid, []))


def _append_manager_turn(session_id: str, role: str, text: str) -> None:
    sid = (session_id or "").strip() or "_anon"
    turns = _MANAGER_TURNS.setdefault(sid, [])
    turns.append({"role": role, "text": text})
    _MANAGER_TURNS[sid] = turns[-_MAX_MANAGER_TURNS:]


async def _load_session_history(session_id: str) -> list[dict[str, str]]:
    """Prefer Redis session history; fall back to process-local dict."""
    sid = (session_id or "").strip()
    if not sid:
        return _history_for_session(sid)
    try:
        import os
        from ..core.redis_session_service import RedisSessionService

        url = os.getenv("REDIS_URL", "")
        if url:
            svc = RedisSessionService(url)
            if getattr(svc, "_use_redis", False):
                sess = await svc.get_session(app_name="manager_chat", user_id="manager", session_id=sid)
                if sess and getattr(sess, "history", None):
                    hist = [{"role": t.get("role", "user"), "text": t.get("text", "")} for t in sess.history]
                    _MANAGER_TURNS[sid] = hist[-_MAX_MANAGER_TURNS:]
                    return list(_MANAGER_TURNS[sid])
    except Exception as e:
        logger.debug("manager session history via Redis skipped: %s", e)
    return _history_for_session(sid)


async def _persist_session_turns(session_id: str, user_text: str, assistant_text: str) -> None:
    sid = (session_id or "").strip()
    _append_manager_turn(sid, "user", user_text)
    _append_manager_turn(sid, "assistant", assistant_text)
    if not sid:
        return
    try:
        import os
        from ..core.redis_session_service import RedisSessionService

        url = os.getenv("REDIS_URL", "")
        if not url:
            return
        svc = RedisSessionService(url)
        if not getattr(svc, "_use_redis", False):
            return
        # Ensure session exists then append
        existing = await svc.get_session(app_name="manager_chat", user_id="manager", session_id=sid)
        if not existing:
            await svc.create_session(app_name="manager_chat", user_id="manager", session_id=sid)
        await svc.append_turn(sid, "user", user_text)
        await svc.append_turn(sid, "assistant", assistant_text)
    except Exception as e:
        logger.debug("manager Redis append skipped: %s", e)


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


def _tts_model_name() -> str:
    import os

    return (
        os.getenv("GEMINI_TTS_MODEL")
        or os.getenv("LLM_MODEL")
        or "gemini-2.5-flash-preview-tts"
    ).strip()


async def synthesize_manager_reply(text: str) -> dict[str, Any]:
    """Gemini TTS → {audioBase64, mimeType}. Raises on failure (caller fail-opens)."""
    import asyncio
    import os
    from ..runtime.ops_llm import llm_api_key
    from google import genai
    from google.genai import types as genai_types

    spoken = (text or "").strip()
    if not spoken:
        raise RuntimeError("empty_tts_text")
    key = llm_api_key()
    if not key:
        raise RuntimeError("LLM_API_KEY_not_configured")

    timeout = int(os.getenv("OPS_LLM_TIMEOUT_SEC", "45"))

    def _generate() -> dict[str, Any]:
        client = genai.Client(api_key=key)
        model = _tts_model_name()
        # Prefer native audio generation when the SDK/model supports it.
        config_kwargs: dict[str, Any] = {}
        try:
            config_kwargs["response_modalities"] = ["AUDIO"]
            speech = getattr(genai_types, "SpeechConfig", None)
            voice = getattr(genai_types, "VoiceConfig", None)
            prebuilt = getattr(genai_types, "PrebuiltVoiceConfig", None)
            if speech and voice and prebuilt:
                config_kwargs["speech_config"] = speech(
                    voice_config=voice(
                        prebuilt_voice_config=prebuilt(voice_name="Kore")
                    )
                )
        except Exception:
            pass
        try:
            config = genai_types.GenerateContentConfig(**config_kwargs)
        except Exception:
            config = None
        if config is not None:
            response = client.models.generate_content(
                model=model,
                contents=spoken[:4000],
                config=config,
            )
        else:
            response = client.models.generate_content(
                model=model,
                contents=spoken[:4000],
            )
        # Extract inline audio bytes from candidates/parts
        audio_bytes: Optional[bytes] = None
        mime = "audio/mp3"
        for cand in getattr(response, "candidates", None) or []:
            content = getattr(cand, "content", None)
            for part in getattr(content, "parts", None) or []:
                inline = getattr(part, "inline_data", None)
                if inline and getattr(inline, "data", None):
                    data = inline.data
                    if isinstance(data, str):
                        audio_bytes = base64.b64decode(data)
                    else:
                        audio_bytes = bytes(data)
                    mime = getattr(inline, "mime_type", None) or mime
                    break
            if audio_bytes:
                break
        if not audio_bytes:
            raise RuntimeError("empty_tts_audio")
        return {
            "audioBase64": base64.b64encode(audio_bytes).decode("ascii"),
            "mimeType": mime or "audio/mp3",
        }

    return await asyncio.wait_for(asyncio.to_thread(_generate), timeout=timeout)


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

    history = await _load_session_history(session_id)
    result = await run_ops_agent(
        "manager_chat",
        "chat",
        _fallback,
        store_id=store_id,
        goal=screened.redacted_text[:800],
        context={
            "store_id": store_id,
            "session_id": session_id,
            "message": screened.redacted_text,
            "history": history,
        },
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

    await _persist_session_turns(session_id, screened.redacted_text, reply)

    runtime = result.get("_runtime") or {}
    out: dict[str, Any] = {
        "reply": reply,
        "sessionId": session_id,
        "transcript": transcript,
        "storeId": store_id,
        "run_id": runtime.get("run_id") or result.get("run_id"),
        "proposals": runtime.get("proposals") or result.get("proposals") or [],
        "tools_used": runtime.get("tools_used") or result.get("tools_used") or [],
        "used_fallback": bool(runtime.get("used_fallback")),
    }
    try:
        audio = await synthesize_manager_reply(reply)
        if audio.get("audioBase64"):
            out["audioBase64"] = audio["audioBase64"]
            out["mimeType"] = audio.get("mimeType") or "audio/mp3"
    except Exception as e:
        logger.warning("manager TTS skipped: %s", e)
    return out
