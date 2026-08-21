# Runbook — masova-support

Operational guide for the AI agent service. No secrets in this file.

## Manual agent triggers

Require header `X-Agent-Api-Key: $AGENT_TRIGGER_API_KEY`.

```bash
export SUPPORT_URL=http://127.0.0.1:8000
export KEY=$AGENT_TRIGGER_API_KEY

curl -s -X POST "$SUPPORT_URL/agents/inventory-reorder/trigger" -H "X-Agent-Api-Key: $KEY"
curl -s -X POST "$SUPPORT_URL/agents/dynamic-pricing/trigger" -H "X-Agent-Api-Key: $KEY"
curl -s -X POST "$SUPPORT_URL/agents/demand-forecast/trigger" -H "X-Agent-Api-Key: $KEY"
# … churn-prevention, shift-optimisation, kitchen-coach
# review-response needs JSON body:
curl -s -X POST "$SUPPORT_URL/agents/review-response/trigger" \
  -H "X-Agent-Api-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"reviewId":"r1","rating":1,"text":"cold food","storeId":"DOM001","orderId":"o1"}'
```

List / resolve proposals (audit only — not final platform execute):

```bash
curl -s "$SUPPORT_URL/agent/proposals?storeId=DOM001&status=PENDING" -H "X-Agent-Api-Key: $KEY"
curl -s -X POST "$SUPPORT_URL/agent/proposals/{id}/resolve" \
  -H "X-Agent-Api-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"status":"APPROVED","note":"done in platform UI"}'
```

---

## Redis down (sessions)

| Symptom | Chat loses multi-turn continuity; new session ids each request or in-memory only |
| Impact | Single-turn chat still works if ADK runner starts; no shared session across replicas |
| Action | 1) Check `REDIS_URL` / Dell Redis. 2) Service falls back to `InMemorySessionService`. 3) Restart Redis; no data recovery for ephemeral in-memory. 4) Confirm logs do not print tokens |

## RabbitMQ down (review agent)

| Symptom | Log: `RabbitMQ consumer not started` — Agent 5 event path off |
| Impact | Low-star reviews not auto-drafted from bus; **manual** `POST /agents/review-response/trigger` still works |
| Action | Fix `RABBITMQ_URL`, ensure exchange/queue `masova.reviews` bindings; restart service |

## Backend 401 / 403 / 5xx

| Code | Meaning | Action |
|------|---------|--------|
| 401 | Bad `AGENT_TOKEN` or customer JWT | Rotate/sync secrets with platform; never log full token |
| 403 | Ownership / ACL denial | Expected when chat user probes another customer's order — user sees friendly denial |
| 5xx | Platform outage | Ops agents should surface tool `ok: false`; rule fallback may still draft offline heuristics |

## LLM outage

| Symptom | `llm_failed:*` in audit; `_runtime.used_fallback=true` |
| Impact | Ops continue via **rule fallback**; chat should degrade to rule/safe reply (no raw provider errors to user) |
| Action | Set `OPS_PREFER_LLM=false` to force rules; restore `LLM_API_KEY`; check provider status |

## AGENT_TOKEN missing

| Symptom | Ops tools return `AGENT_TOKEN not configured`; inventory/reorder skip |
| Impact | No drafts to platform; triggers may return error dicts |
| Action | Set `AGENT_TOKEN` in env; restart. Do not put token in git |

## AGENT_TRIGGER_API_KEY missing

| Symptom | Triggers return **503** (not configured) |
| Action | Set key before exposing service |

## Metrics (logs)

Structured counters (logger `masova_agent.metrics`):

- `runs_total`, `fallback_total`, `proposals_total`, `llm_error_total`, `error_total` per agent

Example grep: `masova_metric agent=inventory_reorder`

## Security checklist

- EXECUTE tools never allowlisted (`patch_menu_price`, etc.)
- Chat identity from JWT only — never LLM `customer_id`
- Secrets never in audit payloads (`raw_token`, `authorization`, … redacted)
- Trigger endpoints require API key
- CI has no live LLM/backend dependency

## Budgets

- Default `max_tool_calls=12` (PolicyEngine / AgentRunRequest / `OPS_MAX_TOOL_CALLS`)
- Ops context pack truncated (~`OPS_CONTEXT_CHARS`, default 8000)
- Pricing + inventory signal gates skip LLM when nothing to do
