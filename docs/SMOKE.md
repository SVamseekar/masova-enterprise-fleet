# Service smoke checks

Optional probes against a **running** fleet service and, if configured, the MaSoVa platform gateway. Skip platform checks when `BACKEND_URL` is unset. Continuous integration must not depend on a live gateway.

## Environment

```bash
export SERVICE_URL="${SERVICE_URL:?deployed service origin}"
export BACKEND_URL="${BACKEND_URL:-}"   # platform gateway; empty = skip
export AGENT_TOKEN="..."                # ops → platform
export AGENT_TRIGGER_API_KEY="..."      # manual triggers
export JWT="..."                        # customer JWT for chat (HS512)
```

Never commit real tokens. Use a gitignored `.env` or the host secret store.

## Script

```bash
./scripts/smoke_backend.sh
```

Or:

```bash
curl -sf "$SERVICE_URL/health"

# Chat without JWT → 401
curl -s -o /dev/null -w "%{http_code}\n" -X POST "$SERVICE_URL/agent/chat" \
  -H 'Content-Type: application/json' \
  -d '{"message":"hi"}'

curl -s -X POST "$SERVICE_URL/agent/chat" \
  -H "Authorization: Bearer $JWT" \
  -H 'Content-Type: application/json' \
  -d '{"message":"What is my loyalty balance?"}'

curl -s -X POST "$SERVICE_URL/agents/inventory-reorder/trigger" \
  -H "X-Agent-Api-Key: $AGENT_TRIGGER_API_KEY"
curl -s -X POST "$SERVICE_URL/agents/dynamic-pricing/trigger" \
  -H "X-Agent-Api-Key: $AGENT_TRIGGER_API_KEY"
```

## Pass criteria

| Check | Expect |
|-------|--------|
| Service `/health` | 200 |
| Chat no JWT | 401 |
| Chat with JWT | 200 + reply (or graceful fallback, never a raw provider error) |
| Trigger without key | 401/403 |
| Trigger with key | 200 + JSON; `_runtime` present when wired |
| Platform unset/offline | Script exits 0 with skipped notes |

See also [SMOKE_CHECKLIST.md](./SMOKE_CHECKLIST.md).
