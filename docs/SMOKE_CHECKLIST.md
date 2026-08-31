# MaSoVa AI live smoke checklist

Run against a deployed fleet service and, optionally, the MaSoVa platform gateway.

**Env (never commit secrets)**

| Variable | Purpose |
|----------|---------|
| `BACKEND_URL` | Platform gateway (omit to skip platform probes) |
| `SERVICE_URL` | This service origin |
| `AGENT_TOKEN` | Ops → backend |
| `AGENT_TRIGGER_API_KEY` | Manual triggers + proposal API |
| `JWT` | Customer HS512 JWT for chat |

```bash
export SERVICE_URL="${SERVICE_URL:?deployed service origin}"
./scripts/smoke_backend.sh
```

## Checklist

| # | Step | Expect | Pass? |
|---|------|--------|-------|
| 1 | `GET $SERVICE_URL/health` | 200 `{"status":"ok",...}` | ☐ |
| 2 | `GET $BACKEND_URL/actuator/health` or `/health` | 200 or documented gateway path | ☐ / offline |
| 3 | `POST /agent/chat` **without** JWT | 401 | ☐ |
| 4 | `POST /agent/chat` with `Authorization: Bearer $JWT` | 200 + reply (or safe fallback, never raw stack) | ☐ |
| 5 | Trigger without `X-Agent-Api-Key` | 401 (or 503 if key unset on server) | ☐ |
| 6 | `POST /agents/inventory-reorder/trigger` with key | 200 JSON; `_runtime` may include `run_id`, `used_fallback` | ☐ |
| 7 | `POST /agents/dynamic-pricing/trigger` with key | 200; no price PATCH side-effect on menu | ☐ |
| 8 | `GET /agent/proposals?storeId=...` with key | 200 list (may be empty) | ☐ |
| 9 | Logs: `agent_audit` / `masova_metric` | No tokens/JWT dumps | ☐ |
| 10 | Notification / proposal path | Manager message includes rationale; propose only | ☐ |
| 11 | Open `/console` | MaSoVa AI brand, 8-agent rail, and chips: Store proof, Run inventory, Pricing signal | ☐ |
| 12 | Click Store proof chip | Counts and low-stock rows come from `/agent/demo/tables/*`, not canned text | ☐ |
| 13 | Click Run inventory chip | Thread shows tool steps; proposal evidence references API inventory IDs/stock numbers | ☐ |
| 14 | Approve proposed PO | Store proof reflects PO status change; no menu price side-effect | ☐ |
| 15 | Decline/reject proposed action | API returns success response; console path does not 500 | ☐ |

## Example curls

```bash
curl -sf "$SERVICE_URL/health"

curl -s -o /dev/null -w "%{http_code}\n" -X POST "$SERVICE_URL/agent/chat" \
  -H 'Content-Type: application/json' -d '{"message":"hi"}'

curl -s -X POST "$SERVICE_URL/agent/chat" \
  -H "Authorization: Bearer $JWT" -H 'Content-Type: application/json' \
  -d '{"message":"What is my loyalty balance?"}'

curl -s -X POST "$SERVICE_URL/agents/inventory-reorder/trigger" \
  -H "X-Agent-Api-Key: $AGENT_TRIGGER_API_KEY"

curl -s "$SERVICE_URL/agent/proposals?status=PENDING" \
  -H "X-Agent-Api-Key: $AGENT_TRIGGER_API_KEY"
```

## Results

Record date, environment, and pass/fail **without secrets** in the change request or operations log. Do not commit probe transcripts.

## Related

- [SMOKE.md](./SMOKE.md) — short optional smoke notes  
- [RUNBOOK.md](./RUNBOOK.md) — outage playbooks  
- [CAPABILITY_MAP.md](./CAPABILITY_MAP.md) — tool ↔ API map  
