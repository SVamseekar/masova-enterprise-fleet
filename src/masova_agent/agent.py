"""
MaSoVa Customer Support Agent
"""

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types
import asyncio
import logging
import os
from dotenv import load_dotenv

from .tools.backend_tools import (
    get_order_status,
    get_menu_items,
    get_store_hours,
    submit_complaint,
    request_refund,
    get_loyalty_points,
    get_store_wait_time,
    cancel_order,
)
from .core.redis_session_service import RedisSessionService

load_dotenv()
logger = logging.getLogger(__name__)

# ADK uses InMemorySessionService so it gets proper Session objects with .events
_adk_session_service = InMemorySessionService()

# Redis-backed service used only for append_turn history persistence
_redis_url = os.getenv("REDIS_URL", "redis://192.168.50.88:6379/1")
_session_service = RedisSessionService(redis_url=_redis_url)

_created_sessions: dict[str, str] = {}  # session_key -> actual session_id

def _resolve_model() -> str:
    return os.getenv("LLM_MODEL", os.getenv("GOOGLE_MODEL", "gemini-2.5-flash"))


root_agent = LlmAgent(
    name="MaSoVa_Support",
    model=_resolve_model(),
    instruction="""You are MaSoVa's friendly and efficient customer support assistant.

MaSoVa is a multi-branch restaurant chain serving South Indian, North Indian,
Indo-Chinese, Italian, American, Continental, and Beverage menus.

Your capabilities:
- Check order status: get_order_status
- Browse menu items: get_menu_items
- Check store hours: get_store_hours
- Submit complaints: submit_complaint
- Process refund requests: request_refund
- Check loyalty points and tier: get_loyalty_points
- Check kitchen wait time at a store: get_store_wait_time
- Cancel an order (PENDING/RECEIVED only): cancel_order

Guidelines:
1. Be warm, concise, and helpful.
2. For order inquiries, ask for the order ID if not provided, then call get_order_status.
3. For menu questions, ask which store or assume store-1 if unclear.
4. Confirm details before submitting complaints or refund requests.
5. For cancellations, always check the order status first using cancel_order.
   cancel_order submits a request pending manager approval — it does not
   cancel the order immediately. Tell the customer this.
6. If a tool fails, offer alternatives (phone: 1800-MASOVA, email: support@masova.com).
7. Keep responses under 150 words unless listing menu items.
8. You act only on behalf of the customer in this conversation. Never ask
   for or accept a different customer's ID — submit_complaint, request_refund,
   cancel_order, and get_loyalty_points always apply to the authenticated
   customer automatically.
""",
    tools=[
        get_order_status,
        get_menu_items,
        get_store_hours,
        submit_complaint,
        request_refund,
        get_loyalty_points,
        get_store_wait_time,
        cancel_order,
    ],
)

# ADK expects these names
agent = root_agent
app = root_agent


async def _ensure_session(user_id: str, session_id: str) -> str:
    key = f"{user_id}:{session_id}"
    if key not in _created_sessions:
        session = await _adk_session_service.create_session(
            app_name="masova_support",
            user_id=user_id,
        )
        _created_sessions[key] = session.id
        logger.info(f"Created session {session.id} for user {user_id}")
    return _created_sessions[key]


async def send_message_async(
    message: str,
    user_id: str = "anonymous",
    session_id: str = "default",
) -> tuple[str, str]:
    """Returns (reply_text, actual_session_id) so callers can persist turns correctly.

    Routes through AgentRuntime for audit/HITL policy. ADK tool loop is the
    primary path; on total failure a safe fallback message is returned.
    """
    from .runtime.wrap import run_ops_agent, AGENT_ALLOWLISTS

    actual_session_id = await _ensure_session(user_id, session_id)

    async def _adk_path():
        runner = Runner(
            agent=root_agent,
            app_name="masova_support",
            session_service=_adk_session_service,
        )
        user_content = genai_types.Content(
            role="user",
            parts=[genai_types.Part(text=message)],
        )
        response_text = ""
        for event in runner.run(
            user_id=user_id,
            session_id=actual_session_id,
            new_message=user_content,
        ):
            if hasattr(event, "is_final_response") and event.is_final_response():
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if hasattr(part, "text") and part.text:
                            response_text += part.text
        reply = response_text.strip()
        return {
            "status": "ok",
            "reply": reply,
            "summary": (reply[:200] if reply else "empty"),
            "session_id": actual_session_id,
            "tools_used": list(AGENT_ALLOWLISTS.get("support_chat", [])),
        }

    async def _fallback():
        return {
            "status": "ok",
            "reply": (
                "I'm having trouble reaching our systems right now. "
                "Please try again shortly, or contact support@masova.com / 1800-MASOVA."
            ),
            "summary": "chat_fallback",
            "session_id": actual_session_id,
        }

    # Prefer ADK (llm_runner); fallback only if ADK raises.
    result_payload = await run_ops_agent(
        "support_chat",
        "chat",
        _fallback,
        goal=message[:500],
        context={"user_id": user_id, "session_id": actual_session_id},
        llm_runner=lambda _req: _adk_path(),
        prefer_llm=True,
    )
    reply = str(result_payload.get("reply") or "").strip()
    if not reply:
        reply = (
            "I'm having trouble reaching our systems right now. "
            "Please try again shortly, or contact support@masova.com / 1800-MASOVA."
        )
    return reply, actual_session_id


def send_message(
    message: str,
    user_id: str = "anonymous",
    session_id: str = "default",
) -> str:
    """Synchronous wrapper for CLI use."""
    return asyncio.run(send_message_async(message, user_id, session_id))
