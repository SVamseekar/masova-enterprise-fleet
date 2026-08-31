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
from typing import Any, Optional

from dotenv import load_dotenv
import fastapi
from fastapi import Depends, FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .agent import send_message_async, _session_service
from .auth import AgentIdentity, bind_identity, reset_identity, verify_customer_jwt
from .runtime.identity import require_scope
from .scheduler.scheduler import scheduler, register_jobs

load_dotenv()
logger = logging.getLogger(__name__)


async def _start_review_consumer():
    """Consume review.created events from RabbitMQ for Agent 5."""
    try:
        import aio_pika
        from .agents.review_response_agent import draft_review_response

        rabbitmq_url = os.getenv("RABBITMQ_URL", "amqp://guest:guest@127.0.0.1:5672/")
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

    from .services.demo_backend import demo_mode
    if demo_mode():
        from pathlib import Path
        from .services.demo_backend import _db_path
        from .runtime import run_store

        db_file = Path(_db_path())
        if not db_file.exists():
            try:
                import importlib.util

                seed_path = Path(__file__).resolve().parents[2] / "scripts" / "seed_demo_data.py"
                spec = importlib.util.spec_from_file_location("seed_demo_data", seed_path)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    mod.seed()
                    logger.info("Seeded demo database at %s", db_file)
            except Exception as e:
                logger.warning("Demo DB missing and seed failed: %s", e)
        run_store.warn_stale_demo_run_log()
        try:
            from .runtime import proposal_store as _proposal_store

            swept = _proposal_store.sweep_stale_open_queue()
            if swept.get("notify") or swept.get("stale"):
                logger.info("Swept stale open proposals: %s", swept)
        except Exception as e:
            logger.warning("Open-queue proposal sweep skipped: %s", e)

    # Best-effort RAG embedding cache warm-up — avoids paying the full
    # per-chunk embedding cost on the first live query (see knowledge/rag.py).
    try:
        from .knowledge.rag import search_ops_manual

        await search_ops_manual("warm up cache")
    except Exception as e:
        logger.warning("RAG cache warm-up skipped: %s", e)

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


@app.middleware("http")
async def rate_limit_middleware(request, call_next):
    path = request.url.path
    if path == "/health" or path.startswith("/console"):
        return await call_next(request)
    from .runtime.rate_limit import check_rate_limit, classify_route_tier, resolve_client_key

    tier = classify_route_tier(path, request.method)
    key = resolve_client_key(
        client_ip=request.client.host if request.client else None,
        auth_header=request.headers.get("Authorization"),
        api_key_header=request.headers.get("X-Agent-Api-Key"),
    )
    allowed = await check_rate_limit(key, tier=tier)
    if not allowed:
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "rate_limited"}, status_code=429)
    return await call_next(request)


# ---------------------------------------------------------------------------
# Chat endpoint (Agent 1)
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    sessionId: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    sessionId: str


class ManagerChatRequest(BaseModel):
    message: Optional[str] = None
    sessionId: Optional[str] = None
    storeId: Optional[str] = None
    store_id: Optional[str] = None
    audioBase64: Optional[str] = None
    mimeType: Optional[str] = None


@app.get("/health")
def health():
    return {"status": "ok", "service": "masova-support-agent"}


@app.get("/agent/ops-contract")
def get_ops_contract():
    """Shared ops invariants for the console (windows, churn, HITL types)."""
    from .core.ops_contract import public_contract

    return public_contract()


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


@app.post("/agent/manager/chat", dependencies=[Depends(require_scope("chat:manager"))])
async def manager_chat(request: ManagerChatRequest):
    """Gemini Chat for the store manager (text or Gemini voice). Not a customer route."""
    from .agents.manager_chat_agent import run_manager_chat

    session_id = request.sessionId or str(uuid.uuid4())
    store_id = await _validate_store_id(request.storeId or request.store_id)
    try:
        return await run_manager_chat(
            request.message or "",
            store_id=store_id,
            session_id=session_id,
            audio_base64=request.audioBase64,
            mime_type=request.mimeType or "audio/webm",
        )
    except Exception as e:
        logger.error("Manager chat error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Manager chat unavailable. Please try again.")


async def _validate_store_id(store_id: Optional[str]) -> Optional[str]:
    """
    Reject a non-empty store_id that isn't a real store, before it reaches
    proposal/run creation. Empty/None passes through unchanged — that's the
    existing "run for every store" fleet-wide trigger behavior, not a store
    reference, so there's nothing to validate.
    """
    if not store_id:
        return store_id
    from .runtime.store_registry import is_known_store

    if not await is_known_store(store_id):
        raise HTTPException(
            status_code=404,
            detail=f"Unknown store_id '{store_id}'. Call GET /agents (or /api/stores) for valid ids.",
        )
    return store_id


# ---------------------------------------------------------------------------
# Agent trigger endpoints (internal/ops — scheduler or manager triggered).
# Gated by a static service API key, not a customer JWT: there is no single
# customer identity to bind these to.
# ---------------------------------------------------------------------------

@app.post("/agents/demand-forecast/trigger", dependencies=[Depends(require_scope("trigger:demand_forecast"))])
async def trigger_demand_forecast(body: Optional[dict] = Body(None)):
    from .agents.demand_forecasting_agent import run_demand_forecast
    payload = body or {}
    store_id = await _validate_store_id(payload.get("storeId") or payload.get("store_id") or None)
    return await run_demand_forecast(store_id=store_id)


@app.post("/agents/inventory-reorder/trigger", dependencies=[Depends(require_scope("trigger:inventory_reorder"))])
async def trigger_inventory_reorder(body: Optional[dict] = Body(None)):
    from .agents.inventory_reorder_agent import run_inventory_reorder

    payload = body or {}
    store_id = await _validate_store_id(payload.get("storeId") or payload.get("store_id") or None)
    return await run_inventory_reorder(store_id=store_id)


@app.post("/agents/churn-prevention/trigger", dependencies=[Depends(require_scope("trigger:churn_prevention"))])
async def trigger_churn_prevention(body: Optional[dict] = Body(None)):
    from .agents.churn_prevention_agent import run_churn_prevention
    payload = body or {}
    store_id = await _validate_store_id(payload.get("storeId") or payload.get("store_id") or None)
    return await run_churn_prevention(store_id=store_id)


@app.post("/agents/review-response/trigger", dependencies=[Depends(require_scope("trigger:review_response"))])
async def trigger_review_response(review_data: dict = Body(...)):
    from .agents.review_response_agent import draft_review_response
    store_id = await _validate_store_id(review_data.get("storeId") or review_data.get("store_id"))
    if store_id:
        review_data["storeId"] = store_id
    return await draft_review_response(review_data)


@app.post("/agents/shift-optimisation/trigger", dependencies=[Depends(require_scope("trigger:shift_optimisation"))])
async def trigger_shift_opt(body: Optional[dict] = Body(None)):
    from .agents.shift_optimisation_agent import run_shift_optimisation
    payload = body or {}
    store_id = await _validate_store_id(payload.get("storeId") or payload.get("store_id") or None)
    return await run_shift_optimisation(store_id=store_id)


@app.post("/agents/kitchen-coach/trigger", dependencies=[Depends(require_scope("trigger:kitchen_coach"))])
async def trigger_kitchen_coach(body: Optional[dict] = Body(None)):
    from .agents.kitchen_coach_agent import run_kitchen_coach
    payload = body or {}
    store_id = await _validate_store_id(payload.get("storeId") or payload.get("store_id") or None)
    return await run_kitchen_coach(store_id=store_id)


@app.post("/agents/dynamic-pricing/trigger", dependencies=[Depends(require_scope("trigger:dynamic_pricing"))])
async def trigger_dynamic_pricing(body: Optional[dict] = Body(None)):
    from .agents.dynamic_pricing_agent import run_dynamic_pricing

    payload = body or {}
    store_id = await _validate_store_id(payload.get("storeId") or payload.get("store_id") or None)
    return await run_dynamic_pricing(store_id=store_id)


# ---------------------------------------------------------------------------
# ActionProposal list / resolve (manager outcome recording — not final execute)
# ---------------------------------------------------------------------------

class ResolveProposalBody(BaseModel):
    status: str  # APPROVED | REJECTED
    note: Optional[str] = None


@app.get("/agent/proposals", dependencies=[Depends(require_scope("read:proposals"))])
async def list_action_proposals(
    storeId: Optional[str] = None,
    status: Optional[str] = None,
    agent: Optional[str] = None,
    type: Optional[str] = None,
    limit: int = 100,
    includeSideEffects: bool = False,
):
    """
    List ActionProposals stored by this service.

    Final business execute still happens in platform UI/backend after a manager
    approves there; this endpoint records local audit outcomes.
    """
    from .runtime import proposal_store

    exclude_side_effects = not includeSideEffects
    return {
        "proposals": proposal_store.list_proposals(
            store_id=storeId,
            status=status,
            agent=agent,
            type=type,
            limit=limit,
            exclude_side_effects=exclude_side_effects,
        ),
        "total": proposal_store.count_proposals(
            store_id=storeId,
            status=status,
            agent=agent,
            type=type,
            exclude_side_effects=exclude_side_effects,
        ),
    }


@app.post(
    "/agent/proposals/{proposal_id}/resolve",
    dependencies=[Depends(require_scope("resolve:proposals"))],
)
async def resolve_action_proposal(proposal_id: str, body: ResolveProposalBody):
    from .runtime import proposal_store
    from .runtime.proposal_apply import apply_approved_proposal, apply_rejected_proposal

    status_upper = (body.status or "").upper()
    if status_upper not in ("APPROVED", "REJECTED"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid resolution status '{body.status}'. Client can only resolve APPROVED or REJECTED.",
        )

    try:
        rec = proposal_store.resolve_proposal(
            proposal_id, status_upper, note=body.note or ""
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not rec:
        raise HTTPException(status_code=404, detail="proposal not found")

    if rec.get("status") == "APPROVED":
        applied = apply_approved_proposal(rec)
        rec["applied"] = applied
    elif rec.get("status") == "REJECTED":
        applied = apply_rejected_proposal(rec, note=body.note or "")
        rec["applied"] = applied

    return rec


# ---------------------------------------------------------------------------
# Agent registry — live catalog of the fleet (Phase 1, Fortified Enterprise Fleet)
# ---------------------------------------------------------------------------

@app.get("/agents", dependencies=[Depends(require_scope("read:registry"))])
async def list_agents():
    """Live agent catalog — every field derived from running code, no static list."""
    from .runtime.registry import build_registry

    return {"agents": build_registry()}


# ---------------------------------------------------------------------------
# Run history + reasoning traces (Phase 3 observability)
# ---------------------------------------------------------------------------

@app.get("/agent/runs", dependencies=[Depends(require_scope("read:runs"))])
async def list_agent_runs(
    agent: Optional[str] = None,
    storeId: Optional[str] = None,
    limit: int = 100,
):
    from .runtime import run_store

    return {
        "runs": run_store.list_runs(agent=agent, store_id=storeId, limit=limit),
        "chain_verified": run_store.verify_chain(),
    }


@app.get("/agent/runs/{run_id}", dependencies=[Depends(require_scope("read:runs"))])
async def get_agent_run(run_id: str):
    from .runtime import run_store

    rec = run_store.get_run_by_id(run_id)
    if not rec:
        raise HTTPException(status_code=404, detail="run not found")
    return rec


# ---------------------------------------------------------------------------
# Demo Console Tables (Allowlisted SQLite Inspection)
# ---------------------------------------------------------------------------

DEMO_TABLE_ALLOWLIST = {
    "inventory",
    "purchase_orders",
    "purchase_order_items",
    "menu_items",
    "customers",
    "orders",
    "reviews",
    "stores",
    "campaigns",
    "staff_shifts",
    "manager_actions",
}

# Safe, hardcoded ORDER BY clauses — never interpolate request input.
_DEMO_TABLE_ORDER = {
    "staff_shifts": "date DESC, start_time ASC",
    "purchase_orders": "created_at DESC",
    "campaigns": "created_at DESC",
    "manager_actions": "created_at DESC",
    "reviews": "created_at DESC",
    "orders": "created_at DESC",
    "inventory": "item_name ASC",
}


@app.get(
    "/agent/demo/tables/{table}",
    dependencies=[Depends(require_scope("read:registry"))],
)
async def get_demo_table_rows(
    table: str,
    limit: int = 50,
    offset: int = 0,
    store_id: Optional[str] = None,
):
    """Inspect allowlisted SQLite tables for the fleet console."""
    from .services.demo_backend import _connect, demo_mode, ensure_allowlisted_table

    if not demo_mode():
        raise HTTPException(status_code=404, detail="demo mode disabled")
    if table not in DEMO_TABLE_ALLOWLIST:
        raise HTTPException(status_code=400, detail=f"table '{table}' not in allowlist")

    empty = {
        "table": table,
        "store_code": None,
        "total": 0,
        "limit": max(1, min(limit, 200)),
        "offset": offset,
        "rows": [],
    }

    conn = _connect()
    try:
        ensure_allowlisted_table(conn, table)
        store_code = None
        if store_id:
            srow = conn.execute("SELECT code FROM stores WHERE id = ? OR code = ?", (store_id, store_id)).fetchone()
            if srow:
                store_code = srow["code"]

        conditions = []
        args: list[Any] = []
        # Check if table has store_id column
        cols = [c[1] for c in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if not cols:
            empty["store_code"] = store_code
            return empty
        if store_id and "store_id" in cols:
            conditions.append("store_id = ?")
            args.append(store_id)
        elif store_id and "primary_store_id" in cols:
            conditions.append("primary_store_id = ?")
            args.append(store_id)
        elif store_id and table == "purchase_order_items":
            conditions.append(
                "purchase_order_id IN (SELECT id FROM purchase_orders WHERE store_id = ?)"
            )
            args.append(store_id)

        where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        total = conn.execute(f"SELECT COUNT(*) FROM {table} {where_sql}", args).fetchone()[0]

        limit_clamped = max(1, min(limit, 200))
        order_sql = _DEMO_TABLE_ORDER.get(table) or ""
        order_clause = f" ORDER BY {order_sql}" if order_sql else ""
        rows = conn.execute(
            f"SELECT * FROM {table} {where_sql}{order_clause} LIMIT ? OFFSET ?",
            args + [limit_clamped, offset],
        ).fetchall()
        return {
            "table": table,
            "store_code": store_code,
            "total": total,
            "limit": limit_clamped,
            "offset": offset,
            "rows": [dict(r) for r in rows],
        }
    finally:
        conn.close()


_CONSOLE_MANAGER_SCOPES = (
    "read:registry",
    "read:runs",
    "read:proposals",
    "resolve:proposals",
    "chat:manager",
)


def _console_demo_key() -> str:
    """Key injected into /console fetches. Legacy master if AGENT_API_KEYS is unset."""
    from .runtime.identity import load_credentials

    creds = load_credentials()
    for cred in creds.values():
        if all(cred.has_scope(scope) for scope in _CONSOLE_MANAGER_SCOPES):
            return cred.key
    return os.getenv("AGENT_TRIGGER_API_KEY", "")


@app.get("/console", response_class=fastapi.responses.HTMLResponse)
async def serve_console():
    """Serve the in-repo live fleet operations console."""
    from pathlib import Path
    from .services.demo_backend import demo_mode

    console_path = Path(__file__).resolve().parent / "static" / "console.html"
    if not console_path.exists():
        raise HTTPException(status_code=404, detail="console not found")
    with open(console_path, "r", encoding="utf-8") as f:
        html = f.read()

    if demo_mode():
        from .services.demo_backend import demo_focus_store_id

        demo_key = _console_demo_key()
        focus_id = demo_focus_store_id()
        attrs = []
        if "data-demo-key=" not in html:
            attrs.append(f'data-demo-key="{demo_key}"')
        if "data-focus-store-id=" not in html:
            attrs.append(f'data-focus-store-id="{focus_id}"')
        if attrs and "<body" in html:
            html = html.replace("<body", "<body " + " ".join(attrs), 1)

    return fastapi.responses.HTMLResponse(content=html, status_code=200)

