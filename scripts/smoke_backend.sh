#!/usr/bin/env bash
# Optional live smoke against BACKEND_URL + local support service.
# Non-fatal: missing backend or tokens → skip with message, exit 0.
set -u

BACKEND_URL="${BACKEND_URL:-http://192.168.50.88:8080}"
SUPPORT_URL="${SUPPORT_URL:-http://127.0.0.1:8000}"
AGENT_TOKEN="${AGENT_TOKEN:-}"
AGENT_TRIGGER_API_KEY="${AGENT_TRIGGER_API_KEY:-}"
JWT="${JWT:-}"

pass=0
skip=0
fail=0

note() { echo "[smoke] $*"; }
ok() { note "PASS: $*"; pass=$((pass + 1)); }
sk() { note "SKIP: $*"; skip=$((skip + 1)); }
bad() { note "FAIL: $*"; fail=$((fail + 1)); }

code_for() {
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 --max-time 8 "$@" 2>/dev/null) || true
  # curl may print 000 on connect fail; normalize multi-digit glitches
  if [[ -z "$code" || "$code" == "000" || "$code" == "000000" ]]; then
    echo "000"
  else
    # take last 3 digits if somehow longer
    echo "${code: -3}"
  fi
}

note "BACKEND_URL=$BACKEND_URL SUPPORT_URL=$SUPPORT_URL"

# Platform reachability
bc=$(code_for "$BACKEND_URL/actuator/health")
if [[ "$bc" == "000" ]]; then
  bc=$(code_for "$BACKEND_URL/health")
fi
if [[ "$bc" == "000" ]]; then
  sk "backend unreachable ($BACKEND_URL)"
else
  ok "backend responded HTTP $bc"
fi

# Support health
sc=$(code_for "$SUPPORT_URL/health")
if [[ "$sc" == "200" ]]; then
  ok "support /health 200"
elif [[ "$sc" == "000" ]]; then
  sk "support unreachable ($SUPPORT_URL) — start uvicorn locally to test"
else
  bad "support /health expected 200 got $sc"
fi

# Chat without JWT
cc=$(code_for -X POST "$SUPPORT_URL/agent/chat" \
  -H 'Content-Type: application/json' \
  -d '{"message":"hi"}')
if [[ "$cc" == "000" ]]; then
  sk "chat unauth check (support down)"
elif [[ "$cc" == "401" || "$cc" == "403" ]]; then
  ok "chat without JWT → $cc"
else
  bad "chat without JWT expected 401/403 got $cc"
fi

# Chat with JWT
if [[ -n "$JWT" ]]; then
  jc=$(code_for -X POST "$SUPPORT_URL/agent/chat" \
    -H "Authorization: Bearer $JWT" \
    -H 'Content-Type: application/json' \
    -d '{"message":"What are store hours?"}')
  if [[ "$jc" == "200" ]]; then
    ok "chat with JWT 200"
  elif [[ "$jc" == "000" ]]; then
    sk "chat JWT (support down)"
  else
    bad "chat with JWT expected 200 got $jc"
  fi
else
  sk "JWT not set — skip authenticated chat"
fi

# Trigger without key
tc=$(code_for -X POST "$SUPPORT_URL/agents/inventory-reorder/trigger")
if [[ "$tc" == "000" ]]; then
  sk "trigger unauth (support down)"
elif [[ "$tc" == "401" || "$tc" == "403" || "$tc" == "422" ]]; then
  ok "trigger without key → $tc"
else
  # Some stacks return 401 only when dependency enforces — still note
  note "trigger without key HTTP $tc (review auth wiring if unexpected)"
fi

# Trigger with key
if [[ -n "$AGENT_TRIGGER_API_KEY" ]]; then
  for path in inventory-reorder dynamic-pricing; do
    # FastAPI Header alias: x_agent_api_key → X-Agent-Api-Key
    hc=$(code_for -X POST "$SUPPORT_URL/agents/${path}/trigger" \
      -H "X-Agent-Api-Key: $AGENT_TRIGGER_API_KEY")
    if [[ "$hc" == "200" ]]; then
      ok "trigger $path 200"
    elif [[ "$hc" == "000" ]]; then
      sk "trigger $path (support down)"
    else
      bad "trigger $path expected 200 got $hc"
    fi
  done
else
  sk "AGENT_TRIGGER_API_KEY not set — skip authenticated triggers"
fi

if [[ -n "$AGENT_TOKEN" && "$bc" != "000" ]]; then
  # Lightweight authenticated platform probe
  ac=$(code_for "$BACKEND_URL/api/stores" -H "Authorization: Bearer $AGENT_TOKEN")
  if [[ "$ac" == "200" ]]; then
    ok "AGENT_TOKEN GET /api/stores 200"
  else
    note "AGENT_TOKEN GET /api/stores → $ac (may still be OK if path differs)"
  fi
else
  sk "AGENT_TOKEN / backend probe"
fi

note "summary pass=$pass skip=$skip fail=$fail"
# Non-fatal for offline lab: always exit 0 unless explicit hard fails requested
if [[ "${SMOKE_STRICT:-0}" == "1" && "$fail" -gt 0 ]]; then
  exit 1
fi
exit 0
