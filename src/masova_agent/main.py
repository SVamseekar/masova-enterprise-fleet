"""
MaSoVa Support Agent — FastAPI REST entry point.

Run:
    uvicorn src.masova_agent.main:app --host 0.0.0.0 --port 8000 --reload
"""

import asyncio
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
import fastapi
from fastapi import Depends, FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .agent import send_message_async, _session_service
from .auth import AgentIdentity, bind_identity, reset_identity, verify_customer_jwt, verify_trigger_api_key
from .scheduler.scheduler import scheduler, register_jobs

load_dotenv()
logger = logging.getLogger(__name__)


async def _start_review_consumer():
    """Consume review.created events from RabbitMQ for Agent 5."""
    try:
        import aio_pika
        from .agents.review_response_agent import draft_review_response

        rabbitmq_url = os.getenv("RABBITMQ_URL", "amqp://guest:guest@192.168.50.88:5672/")
        connection = await aio_pika.connect_robust(rabbitmq_url)
        channel = await connection.channel()
        queue = await channel.declare_queue("masova.agent.reviews", durable=True)
        exchange = await channel.declare_exchange("masova.reviews.exchange", aio_pika.ExchangeType.TOPIC, durable=True)
        await queue.bind(exchange, "review.created")

        logger.info("RabbitMQ review consumer started")

        async for message in queue:
            async with message.process():
                review_data = json.loads(message.body)
                if review_data.get("rating", 5) <= 3:
                    await draft_review_response(review_data)
    except Exception as e:
        logger.warning("RabbitMQ consumer not started (%s) — review response agent disabled", e)


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    # Reload config to pick up any .env changes made after module import
    from .utils.config import reload_config
    reload_config()

    # Start scheduler
    scheduler.start()
    register_jobs()
    logger.info("APScheduler started with %d jobs", len(scheduler.get_jobs()))

    # Start RabbitMQ consumer; hold reference so it is not GC'd
    _review_task = asyncio.create_task(_start_review_consumer())

    yield

    # Shutdown
    _review_task.cancel()
    scheduler.shutdown(wait=False)
    logger.info("APScheduler stopped")


app = FastAPI(
    title="MaSoVa Support Agent",
    description="AI-powered customer support for MaSoVa restaurant chain.",
    version="0.3.0",
    lifespan=lifespan,
)

_origins = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://localhost:3000,http://localhost:8080",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Chat endpoint (Agent 1)
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    sessionId: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    sessionId: str


@app.get("/health")
def health():
    return {"status": "ok", "service": "masova-support-agent"}


@app.post("/agent/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, identity: AgentIdentity = Depends(verify_customer_jwt)):
    """Send a message to the MaSoVa support agent, authenticated as the caller's verified identity."""
    if not request.message or not request.message.strip():
        raise HTTPException(status_code=400, detail="message must not be empty")

    session_id = request.sessionId or str(uuid.uuid4())
    user_id = identity.user_id

    # Bind the verified identity for the duration of this request so tool
    # functions (submit_complaint, cancel_order, etc.) act on the real
    # authenticated customer rather than any LLM-parsed argument.
    token = bind_identity(identity)
    try:
        reply, actual_session_id = await send_message_async(
            message=request.message.strip(),
            user_id=user_id,
            session_id=session_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Agent error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Agent unavailable. Please try again.")
    finally:
        reset_identity(token)

    await _session_service.append_turn(actual_session_id, "user", request.message.strip())
    await _session_service.append_turn(actual_session_id, "assistant", reply)

    return ChatResponse(reply=reply, sessionId=session_id)


# ---------------------------------------------------------------------------
# Agent trigger endpoints (internal/ops — scheduler or manager triggered).
# Gated by a static service API key, not a customer JWT: there is no single
# customer identity to bind these to.
# ---------------------------------------------------------------------------

@app.post("/agents/demand-forecast/trigger", dependencies=[Depends(verify_trigger_api_key)])
async def trigger_demand_forecast():
    from .agents.demand_forecasting_agent import run_demand_forecast
    return await run_demand_forecast()


@app.post("/agents/inventory-reorder/trigger", dependencies=[Depends(verify_trigger_api_key)])
async def trigger_inventory_reorder():
    from .agents.inventory_reorder_agent import run_inventory_reorder
    return await run_inventory_reorder()


@app.post("/agents/churn-prevention/trigger", dependencies=[Depends(verify_trigger_api_key)])
async def trigger_churn_prevention():
    from .agents.churn_prevention_agent import run_churn_prevention
    return await run_churn_prevention()


@app.post("/agents/review-response/trigger", dependencies=[Depends(verify_trigger_api_key)])
async def trigger_review_response(review_data: dict = Body(...)):
    from .agents.review_response_agent import draft_review_response
    return await draft_review_response(review_data)


@app.post("/agents/shift-optimisation/trigger", dependencies=[Depends(verify_trigger_api_key)])
async def trigger_shift_opt():
    from .agents.shift_optimisation_agent import run_shift_optimisation
    return await run_shift_optimisation()


@app.post("/agents/kitchen-coach/trigger", dependencies=[Depends(verify_trigger_api_key)])
async def trigger_kitchen_coach():
    from .agents.kitchen_coach_agent import run_kitchen_coach
    return await run_kitchen_coach()


@app.post("/agents/dynamic-pricing/trigger", dependencies=[Depends(verify_trigger_api_key)])
async def trigger_dynamic_pricing():
    from .agents.dynamic_pricing_agent import run_dynamic_pricing
    return await run_dynamic_pricing()


# ---------------------------------------------------------------------------
# ActionProposal list / resolve (manager outcome recording — not final execute)
# ---------------------------------------------------------------------------

class ResolveProposalBody(BaseModel):
    status: str  # APPROVED | REJECTED
    note: Optional[str] = None


@app.get("/agent/proposals", dependencies=[Depends(verify_trigger_api_key)])
async def list_action_proposals(
    storeId: Optional[str] = None,
    status: Optional[str] = None,
    agent: Optional[str] = None,
    limit: int = 100,
):
    """
    List ActionProposals stored by this service.

    Final business execute still happens in platform UI/backend after a manager
    approves there; this endpoint records local audit outcomes.
    """
    from .runtime import proposal_store

    return {
        "proposals": proposal_store.list_proposals(
            store_id=storeId, status=status, agent=agent, limit=limit
        )
    }


@app.post(
    "/agent/proposals/{proposal_id}/resolve",
    dependencies=[Depends(verify_trigger_api_key)],
)
async def resolve_action_proposal(proposal_id: str, body: ResolveProposalBody):
    from .runtime import proposal_store

    try:
        rec = proposal_store.resolve_proposal(
            proposal_id, body.status, note=body.note or ""
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not rec:
        raise HTTPException(status_code=404, detail="proposal not found")
    return rec
