# Design: Manager Gemini Chat + contract honesty

Status: **approved for implementation** (2026-08-29).
Track: All Things Agentic — Fortified Enterprise Fleet.
Inherits: hackathon constraints; this file wins on UI/voice/manager-only.

## Product

MaSoVa AI is a **manager-only** Gemini Chat: one conversation (text or Gemini voice) in the existing Grok-bot chrome (`docs/hackathon/masova-ai-console.html`). The eight specialists, synthetic SQLite world, HITL proposals, and store proof run behind that chat. Not a customer bot. Not a second voice stack.

## Manager door

- `POST /agent/manager/chat` — `X-Agent-Api-Key` with scope `chat:manager` (`*` includes it).
- Body: `{ message?, sessionId?, storeId?, audioBase64?, mimeType? }`.
- Gemini (same `LLM_MODEL` / 3.5+) uses ops tools + `run_inventory_reorder` / `run_dynamic_pricing`. Voice audio is transcribed by Gemini then enters the same loop.
- Console composer and mic call **only** this endpoint. Customer `POST /agent/chat` stays for JWT diners; this product does not use it.

## Contract / hardcoding (same pass)

Strip Dell LAN defaults from `src/`. Unify kitchen active statuses. Draft POs via `POST /api/purchase-orders`. CAPABILITY_MAP matches code. Empty rule runs mint **no** PENDING card. Console hydrates live PENDING. Pricing/inventory honor `storeId` (unknown id → that id only, never silent fleet). Refund fixture matches platform enum (no `APPROVED`). Dockerfile copies console + demo DB.
