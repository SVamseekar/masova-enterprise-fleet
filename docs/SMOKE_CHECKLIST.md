# Live smoke checklist

Run against a running support process + optional Dell/staging platform.

**Env (never commit secrets)**

| Variable | Purpose |
|----------|---------|
| `BACKEND_URL` | Platform gateway (default `http://192.168.50.88:8080`) |
| `SUPPORT_URL` | This service (default `http://127.0.0.1:8000`) |
| `AGENT_TOKEN` | Ops → backend |
| `AGENT_TRIGGER_API_KEY` | Manual triggers + proposal API |
| `JWT` | Customer HS512 JWT for chat |

```bash
# Start support (separate terminal)
uvicorn src.masova_agent.main:app --host 0.0.0.0 --port 8000

# Optional automated probe (non-fatal if offline; set SMOKE_STRICT=1 to fail hard)
./scripts/smoke_backend.sh
```

## Checklist

| # | Step | Expect | Pass? |
|---|------|--------|-------|
| 1 | `GET $SUPPORT_URL/health` | 200 `{"status":"ok",...}` | ☐ |
| 2 | `GET $BACKEND_URL/actuator/health` or `/health` | 200 or documented gateway path | ☐ / offline |
| 3 | `POST /agent/chat` **without** JWT | 401 | ☐ |
| 4 | `POST /agent/chat` with `Authorization: Bearer $JWT` | 200 + reply (or safe fallback, never raw stack) | ☐ |
| 5 | Trigger without `X-Agent-Api-Key` | 401 (or 503 if key unset on server) | ☐ |
| 6 | `POST /agents/inventory-reorder/trigger` with key | 200 JSON; `_runtime` may include `run_id`, `used_fallback` | ☐ |
| 7 | `POST /agents/dynamic-pricing/trigger` with key | 200; no price PATCH side-effect on menu | ☐ |
| 8 | `GET /agent/proposals?storeId=...` with key | 200 list (may be empty) | ☐ |
| 9 | Logs: `agent_audit` / `masova_metric` | No tokens/JWT dumps | ☐ |
| 10 | Notification / proposal path | Manager message includes rationale; propose only | ☐ |

## Example curls

```bash
curl -sf "$SUPPORT_URL/health"

curl -s -o /dev/null -w "%{http_code}\n" -X POST "$SUPPORT_URL/agent/chat" \
  -H 'Content-Type: application/json' -d '{"message":"hi"}'

curl -s -X POST "$SUPPORT_URL/agent/chat" \
  -H "Authorization: Bearer $JWT" -H 'Content-Type: application/json' \
  -d '{"message":"What is my loyalty balance?"}'

curl -s -X POST "$SUPPORT_URL/agents/inventory-reorder/trigger" \
  -H "X-Agent-Api-Key: $AGENT_TRIGGER_API_KEY"

curl -s "$SUPPORT_URL/agent/proposals?status=PENDING" \
  -H "X-Agent-Api-Key: $AGENT_TRIGGER_API_KEY"
```

## Results log (optional)

Record date, environment, and pass/fail without secrets in `docs/SMOKE_RESULTS.md` or the PR body.

### Lab run (this program)

| Date | Env | Notes |
|------|-----|-------|
| 2026-08-08 | Local + Dell IP defaults | Support process not running during automated script → support probes skipped/fail; backend probe non-200 offline. CI remains green without live deps. Re-run checklist when lab is up. |

## Related

- [SMOKE.md](./SMOKE.md) — short optional smoke notes  
- [RUNBOOK.md](./RUNBOOK.md) — outage playbooks  
- [CAPABILITY_MAP.md](./CAPABILITY_MAP.md) — tool ↔ API map  
