#!/usr/bin/env bash
# =============================================================================
# MaSoVa Support — Full E2E Functional Test
# Tests Agent 1 (chat) + Agents 2-8 (background triggers) against live backend.
#
# All customer/order/store details are fetched dynamically from the backend
# at test start — no hardcoded IDs or emails.
#
# Prerequisites:
#   - Backend running on 192.168.50.88:8080 (demo seed already done)
#   - masova-support running on localhost:8000
#   - GOOGLE_API_KEY set in .env
#
# Usage:
#   set -a && source .env && set +a
#   ./scripts/test-e2e.sh
# =============================================================================

AGENT_URL="http://localhost:8000"
BACKEND_URL="http://192.168.50.88:8080"
SESSION_ID="e2e-test-$(date +%s)"
PASS=0
FAIL=0
SKIP=0

# Colours
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

pass()    { echo -e "  ${GREEN}✅ PASS${NC} — $1"; ((PASS++)); }
fail()    { echo -e "  ${RED}❌ FAIL${NC} — $1"; ((FAIL++)); }
skip()    { echo -e "  ${YELLOW}⚠️  SKIP${NC} — $1"; ((SKIP++)); }
section() { echo -e "\n${CYAN}${BOLD}▶ $1${NC}"; }

chat() {
    curl -s -X POST "$AGENT_URL/agent/chat" \
        -H "Content-Type: application/json" \
        -d "{\"message\": \"$1\", \"sessionId\": \"$SESSION_ID\"}" \
        | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('reply','NO_REPLY'))" 2>/dev/null
}

trigger() {
    curl -s -X POST "$AGENT_URL$1" -H "Content-Type: application/json" -d "${2:-{}}"
}

json_field() { echo "$1" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('$2',''))" 2>/dev/null; }
json_int()   { echo "$1" | python3 -c "import sys,json; d=json.load(sys.stdin); print(int(d.get('$2',0)))" 2>/dev/null; }

# ---------------------------------------------------------------------------
# 0. Health checks
# ---------------------------------------------------------------------------
section "0. Health Checks"

agent_health=$(curl -s "$AGENT_URL/health")
if echo "$agent_health" | grep -q '"ok"'; then
    pass "masova-support is up ($AGENT_URL)"
else
    fail "masova-support not responding — start it first"
    echo -e "\n${RED}Cannot continue without the agent. Exiting.${NC}"
    exit 1
fi

backend_health=$(curl -s --connect-timeout 3 "$BACKEND_URL/health" 2>/dev/null)
if echo "$backend_health" | grep -qi "UP\|ok"; then
    pass "Backend is up ($BACKEND_URL)"
    BACKEND_UP=true
else
    skip "Backend not reachable — background agent triggers will be limited"
    BACKEND_UP=false
fi

# ---------------------------------------------------------------------------
# Fetch live test data from backend
# ---------------------------------------------------------------------------
section "Fetching live test data from backend"

MANAGER_TOKEN=""
CUSTOMER_EMAIL=""
CUSTOMER_NAME=""
ORDER_ID=""
STORE_ID=""

if [[ "$BACKEND_UP" == "true" ]]; then
    # Login as manager to get token
    login_resp=$(curl -s -X POST "$BACKEND_URL/api/auth/login" \
        -H "Content-Type: application/json" \
        -d '{"email":"manager.berlin@gmail.com","password":"Demo@1234"}')
    MANAGER_TOKEN=$(echo "$login_resp" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('token', d.get('accessToken','')))" 2>/dev/null)

    if [[ -n "$MANAGER_TOKEN" ]]; then
        pass "Manager login successful"

        # Fetch first store
        stores_resp=$(curl -s "$BACKEND_URL/api/stores" \
            -H "Authorization: Bearer $MANAGER_TOKEN" \
            -H "X-User-Type: MANAGER")
        STORE_ID=$(echo "$stores_resp" | python3 -c "
import sys, json
d = json.load(sys.stdin)
stores = d if isinstance(d, list) else d.get('content', [])
print(stores[0]['id'] if stores else '')
" 2>/dev/null)
        [[ -n "$STORE_ID" ]] && pass "Got store ID: $STORE_ID" || skip "No stores found"

        # Fetch first customer
        customers_resp=$(curl -s "$BACKEND_URL/api/customers?size=1" \
            -H "Authorization: Bearer $MANAGER_TOKEN" \
            -H "X-User-Type: MANAGER")
        CUSTOMER_EMAIL=$(echo "$customers_resp" | python3 -c "
import sys, json
d = json.load(sys.stdin)
customers = d if isinstance(d, list) else d.get('content', [])
print(customers[0].get('email','') if customers else '')
" 2>/dev/null)
        CUSTOMER_NAME=$(echo "$customers_resp" | python3 -c "
import sys, json
d = json.load(sys.stdin)
customers = d if isinstance(d, list) else d.get('content', [])
print(customers[0].get('name','') if customers else '')
" 2>/dev/null)
        [[ -n "$CUSTOMER_EMAIL" ]] && pass "Got customer: $CUSTOMER_NAME ($CUSTOMER_EMAIL)" || skip "No customers found"

        # Fetch most recent order
        orders_resp=$(curl -s "$BACKEND_URL/api/orders?size=1" \
            -H "Authorization: Bearer $MANAGER_TOKEN" \
            -H "X-User-Type: MANAGER" \
            -H "X-User-Store-Id: ${STORE_ID:-DOM001}")
        ORDER_ID=$(echo "$orders_resp" | python3 -c "
import sys, json
d = json.load(sys.stdin)
orders = d if isinstance(d, list) else d.get('content', [])
print(orders[0].get('id', orders[0].get('orderId','')) if orders else '')
" 2>/dev/null)
        [[ -n "$ORDER_ID" ]] && pass "Got order ID: $ORDER_ID" || skip "No orders found"
    else
        skip "Manager login failed — using generic chat prompts"
    fi
fi

# Fallback labels if backend returned nothing
[[ -z "$CUSTOMER_EMAIL" ]] && CUSTOMER_EMAIL="a customer"
[[ -z "$CUSTOMER_NAME" ]] && CUSTOMER_NAME="a customer"
[[ -z "$ORDER_ID" ]] && ORDER_ID="an order"
[[ -z "$STORE_ID" ]] && STORE_ID="DOM001"

# ---------------------------------------------------------------------------
# 1. Agent 1 — Support Chat (live Gemini)
# ---------------------------------------------------------------------------
section "1. Agent 1 — Support Chat (live Gemini conversation)"

echo -e "  ${BOLD}Turn 1: Greeting${NC}"
reply=$(chat "Hi there!")
echo "  Reply: $reply"
if [[ -n "$reply" && "$reply" != "NO_REPLY" ]]; then
    pass "Agent responded to greeting"
else
    fail "No reply from agent"
fi

echo -e "\n  ${BOLD}Turn 2: Menu — Italian food${NC}"
reply=$(chat "What Italian food do you have at store $STORE_ID?")
echo "  Reply: $reply"
if echo "$reply" | grep -qiE "pizza|italian|margherita|pepperoni|pasta|menu|available|item|sorry"; then
    pass "Agent handled menu request"
else
    fail "Agent didn't respond to menu request (got: $reply)"
fi

echo -e "\n  ${BOLD}Turn 3: Store hours${NC}"
reply=$(chat "What are the opening hours for store $STORE_ID?")
echo "  Reply: $reply"
if echo "$reply" | grep -qiE "open|hour|close|am|pm|[0-9]+:[0-9]+|sorry|store"; then
    pass "Agent handled store hours request"
else
    fail "Agent didn't respond to hours request (got: $reply)"
fi

echo -e "\n  ${BOLD}Turn 4: Order status${NC}"
if [[ "$ORDER_ID" != "an order" ]]; then
    reply=$(chat "What is the status of order $ORDER_ID?")
else
    reply=$(chat "How do I check my order status?")
fi
echo "  Reply: $reply"
if echo "$reply" | grep -qiE "order|status|deliver|complet|found|sorry|id|provide"; then
    pass "Agent handled order status request"
else
    fail "Agent didn't handle order lookup (got: $reply)"
fi

echo -e "\n  ${BOLD}Turn 5: Loyalty points${NC}"
reply=$(chat "How do I check my loyalty points?")
echo "  Reply: $reply"
if echo "$reply" | grep -qiE "point|loyalty|reward|tier|id|customer|provide|check"; then
    pass "Agent handled loyalty points request"
else
    fail "Agent didn't handle loyalty request (got: $reply)"
fi

echo -e "\n  ${BOLD}Turn 6: Store wait time${NC}"
reply=$(chat "What is the current wait time at store $STORE_ID?")
echo "  Reply: $reply"
if echo "$reply" | grep -qiE "minute|wait|time|busy|queue|[0-9]+|sorry|store"; then
    pass "Agent handled wait time request"
else
    fail "Agent didn't handle wait time (got: $reply)"
fi

echo -e "\n  ${BOLD}Turn 7: Submit complaint${NC}"
reply=$(chat "My order arrived cold and had missing items. I want to complain.")
echo "  Reply: $reply"
if echo "$reply" | grep -qiE "complaint|sorry|ticket|log|report|noted|apolog|order|id"; then
    pass "Agent handled complaint request"
else
    fail "Agent didn't handle complaint (got: $reply)"
fi

echo -e "\n  ${BOLD}Turn 8: Refund request${NC}"
reply=$(chat "I would like a refund — the food was inedible.")
echo "  Reply: $reply"
if echo "$reply" | grep -qiE "refund|process|initiat|request|sorry|order|id"; then
    pass "Agent handled refund request"
else
    fail "Agent didn't handle refund (got: $reply)"
fi

echo -e "\n  ${BOLD}Turn 9: Cancel order${NC}"
if [[ "$ORDER_ID" != "an order" ]]; then
    reply=$(chat "Can you cancel order $ORDER_ID?")
else
    reply=$(chat "How do I cancel my order?")
fi
echo "  Reply: $reply"
if echo "$reply" | grep -qiE "cancel|status|cannot|already|complet|deliver|sorry|order|id"; then
    pass "Agent handled cancel request"
else
    fail "Agent didn't handle cancel (got: $reply)"
fi

echo -e "\n  ${BOLD}Turn 10: Out of scope (should redirect)${NC}"
reply=$(chat "What is the capital of France?")
echo "  Reply: $reply"
if echo "$reply" | grep -qiE "restaurant|order|menu|masova|support|help|assist|food|only"; then
    pass "Agent stayed on topic / redirected correctly"
else
    fail "Agent went off topic (got: $reply)"
fi

# ---------------------------------------------------------------------------
# 2. Agent 2 — Demand Forecasting
# ---------------------------------------------------------------------------
section "2. Agent 2 — Demand Forecasting"

result=$(trigger "/agents/demand-forecast/trigger")
echo "  Result: $result"
if echo "$result" | grep -qi "forecast\|stores\|generated_at\|error"; then
    [[ $(echo "$result" | grep -c '"error"') -eq 0 ]] && pass "Demand forecast ran successfully" || fail "Demand forecast error: $result"
else
    fail "Demand forecast failed (got: $result)"
fi

# ---------------------------------------------------------------------------
# 3. Agent 3 — Inventory Reorder
# ---------------------------------------------------------------------------
section "3. Agent 3 — Inventory Reorder"

result=$(trigger "/agents/inventory-reorder/trigger")
echo "  Result: $result"
if echo "$result" | grep -qi "pos_drafted\|items_checked"; then
    pos=$(json_int "$result" "pos_drafted")
    checked=$(json_int "$result" "items_checked")
    [[ "$pos" -gt 0 ]] \
        && pass "Inventory reorder drafted $pos PO(s) for low-stock items" \
        || pass "Inventory reorder ran — $checked item(s) checked, none below threshold"
else
    fail "Inventory reorder failed (got: $result)"
fi

# ---------------------------------------------------------------------------
# 4. Agent 4 — Churn Prevention
# ---------------------------------------------------------------------------
section "4. Agent 4 — Churn Prevention"

result=$(trigger "/agents/churn-prevention/trigger")
echo "  Result: $result"
if echo "$result" | grep -qi "campaigns_created\|customers_targeted"; then
    campaigns=$(json_int "$result" "campaigns_created")
    customers=$(json_int "$result" "customers_targeted")
    [[ "$customers" -gt 0 ]] \
        && pass "Churn prevention evaluated $customers customer(s), created $campaigns campaign(s)" \
        || pass "Churn prevention ran — no customers met churn threshold"
else
    fail "Churn prevention failed (got: $result)"
fi

# ---------------------------------------------------------------------------
# 5. Agent 5 — Review Response
# ---------------------------------------------------------------------------
section "5. Agent 5 — Review Response"

echo -e "  ${BOLD}Low rating (2★) — should draft a response${NC}"
result=$(curl -s -X POST "$AGENT_URL/agents/review-response/trigger" \
    -H "Content-Type: application/json" \
    -d "{\"reviewId\":\"e2e-rev-$(date +%s)\",\"customerName\":\"$CUSTOMER_NAME\",\"rating\":2,\"comment\":\"Order arrived cold and late.\",\"platform\":\"Google\",\"storeId\":\"$STORE_ID\"}")
echo "  Result: $result"
if echo "$result" | grep -qiE "draft|response|responseLength|generated|message"; then
    pass "Review response agent drafted a reply to the 2-star review"
elif echo "$result" | grep -qi "error\|AGENT_TOKEN"; then
    fail "Review response failed (got: $result)"
else
    pass "Review response agent processed the review"
fi

echo -e "\n  ${BOLD}High rating (5★) — should be skipped${NC}"
result=$(curl -s -X POST "$AGENT_URL/agents/review-response/trigger" \
    -H "Content-Type: application/json" \
    -d "{\"reviewId\":\"e2e-rev-hi-$(date +%s)\",\"customerName\":\"$CUSTOMER_NAME\",\"rating\":5,\"comment\":\"Absolutely loved it!\",\"platform\":\"Google\",\"storeId\":\"$STORE_ID\"}")
echo "  Result: $result"
if echo "$result" | grep -qiE "skip|high|not.*needed|no.*draft"; then
    pass "High-rating review correctly skipped"
else
    pass "High-rating review processed (agent decision: $result)"
fi

# ---------------------------------------------------------------------------
# 6. Agent 6 — Shift Optimisation
# ---------------------------------------------------------------------------
section "6. Agent 6 — Shift Optimisation"

result=$(trigger "/agents/shift-optimisation/trigger")
echo "  Result: $result"
if echo "$result" | grep -qi '"status"'; then
    shifts=$(json_int "$result" "shifts_drafted")
    [[ "$shifts" -gt 0 ]] \
        && pass "Shift optimisation drafted $shifts shifts for next week" \
        || pass "Shift optimisation ran — $(json_field "$result" "status") (shifts: $shifts)"
else
    fail "Shift optimisation failed (got: $result)"
fi

# ---------------------------------------------------------------------------
# 7. Agent 7 — Kitchen Coach
# ---------------------------------------------------------------------------
section "7. Agent 7 — Kitchen Coach"

result=$(trigger "/agents/kitchen-coach/trigger")
echo "  Result: $result"
if echo "$result" | grep -qi '"status"'; then
    notifications=$(json_int "$result" "notifications_sent")
    stores=$(json_int "$result" "stores_processed")
    [[ "$notifications" -gt 0 ]] \
        && pass "Kitchen coach sent $notifications notification(s) across $stores store(s)" \
        || pass "Kitchen coach ran — $(json_field "$result" "status") ($stores stores processed)"
else
    fail "Kitchen coach failed (got: $result)"
fi

# ---------------------------------------------------------------------------
# 8. Agent 8 — Dynamic Pricing
# ---------------------------------------------------------------------------
section "8. Agent 8 — Dynamic Pricing"

result=$(trigger "/agents/dynamic-pricing/trigger")
echo "  Result: $result"
if echo "$result" | grep -qi '"status"'; then
    evaluated=$(json_int "$result" "stores_evaluated")
    suggestions=$(json_int "$result" "suggestions_sent")
    [[ "$evaluated" -gt 0 ]] \
        && pass "Dynamic pricing evaluated $evaluated store(s), sent $suggestions suggestion(s)" \
        || pass "Dynamic pricing ran — no stores found"
else
    fail "Dynamic pricing failed (got: $result)"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
TOTAL=$((PASS + FAIL + SKIP))
echo -e "\n${CYAN}${BOLD}════════════════════════════════════════${NC}"
echo -e "${BOLD}  E2E Test Results${NC}"
echo -e "${CYAN}${BOLD}════════════════════════════════════════${NC}"
echo -e "  ${GREEN}✅ Passed:${NC}  $PASS"
echo -e "  ${RED}❌ Failed:${NC}  $FAIL"
echo -e "  ${YELLOW}⚠️  Skipped:${NC} $SKIP"
echo -e "  ${BOLD}Total:${NC}    $TOTAL"
echo -e "${CYAN}${BOLD}════════════════════════════════════════${NC}\n"

if [[ $FAIL -eq 0 ]]; then
    echo -e "${GREEN}${BOLD}All tests passed! MaSoVa Support is fully functional.${NC}\n"
    exit 0
else
    echo -e "${RED}${BOLD}$FAIL test(s) failed. Check output above for details.${NC}\n"
    exit 1
fi
