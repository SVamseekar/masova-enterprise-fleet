# 18 grounded ActionProposal scenarios — EU market

Field shapes match the real MaSoVa platform (shared-models / commerce-service / logistics-service / payment-service), verified against the actual entity definitions, not the drifted assumptions in masova-support's `backend_contracts.py` fixtures. Market: Lisbon, Portugal — EUR pricing (cents, matching the platform's integer-minor-units convention), EU operating context, GDPR-relevant customer handling made explicit where it applies.

Schema per proposal (matches `runtime/models.py` `ActionProposal`):
`type, store_id, agent, risk=PROPOSE, summary, rationale, payload{}, proposal_id, idempotency_key, status`

Store used throughout: `store_id: "68a1f2c9e4b0a1234567890a"` (Mongo ObjectId), `code: "DOM014"` (Lisbon — Alfama).

---

## dynamic-pricing (4)

1. **Slot discount, demand dip**
   summary: "Drop large-pizza price 8% for Tue–Wed 17:00–19:00 window"
   rationale: "Demand model shows 34% dip in that slot vs. 8-week average; three comparable DOM stores raised order volume 19% with a similar discount. Confidence: high."
   payload: `{menuItemId: "mi_lg_pizza_pepperoni", basePrice: 1290, proposedBasePrice: 1187, category: "PIZZA"}` — cents (EUR 12.90 → EUR 11.87), matching the platform's integer-minor-units convention.
   idempotency_key: `dp_20260820_dom014_slot17`

2. **Weather-driven surge pricing**
   summary: "Raise delivery fee 12% during forecast heavy-rain window, Thu 18:00–21:00"
   rationale: "IPMA forecast shows 80%+ precipitation probability; historical DOM-store data shows delivery demand +41% and rider availability −22% in comparable Lisbon rain events. Fee increase offsets rider incentive cost, not margin."
   payload: `{deliveryFeeCurrent: 290, deliveryFeeProposed: 325}`
   idempotency_key: `dp_20260821_dom014_rain`

3. **Competitor price match**
   summary: "Match nearby competitor's €7.90 combo pricing on Family Meal Combo"
   rationale: "Competitor within 1.2km dropped equivalent combo price 6 days ago; DOM014 combo order share down 8% since. Recommend matching, not undercutting, to protect margin."
   payload: `{menuItemId: "mi_family_combo", basePrice: 890, proposedBasePrice: 790}`
   idempotency_key: `dp_20260822_dom014_combo`

4. **Off-peak underpricing risk flagged, NOT recommended for change**
   summary: "Hold pricing on breakfast tier despite 15% margin softness"
   rationale: "Margin softness driven by ingredient cost (imported mozzarella +9% wholesale this week per EU supplier invoice, tariff-linked), not demand elasticity. A price change here would suppress the one growing daypart (+22% YoY, tourist season). Proposing supplier renegotiation instead — see inventory-reorder proposal for same window."
   payload: `{action: "hold", flaggedCategory: "BREAKFAST"}`
   idempotency_key: `dp_20260823_dom014_hold_breakfast`

---

## inventory-reorder (3)

5. **Standard low-stock PO**
   summary: "Draft PO — mozzarella (18kg), tomato base (12L)"
   rationale: "Both items projected to fall below minimumStock threshold before next scheduled delivery. Supplier lead time: 1 business day."
   payload: `{items: [{itemCode: "ING-MOZZ-18", itemName: "Mozzarella", currentStock: 6.2, minimumStock: 10, unit: "kg"}, {itemCode: "ING-TOM-12L", itemName: "Tomato Base", currentStock: 3.1, minimumStock: 6, unit: "L"}], supplierId: "sup_dairy_pt_04"}`
   idempotency_key: `inv_20260820_dom014_reorder`

6. **Emergency reorder, supplier delay risk**
   summary: "Escalate PO for buffalo mozzarella to backup supplier — primary 2 days late, customs hold"
   rationale: "primarySupplierId sup_dairy_pt_04 confirmed delivery delay via webhook 09:14, EU customs inspection on imported lot; currentStock will hit 0 by Thu lunch service at current draw rate. alternativeSupplierIds has one domestic backup with same-day capacity at 8% cost premium — no cross-border delay risk."
   payload: `{itemCode: "ING-BUFMOZZ-9", primarySupplierId: "sup_dairy_pt_04", fallbackSupplierId: "sup_dairy_pt_alt_11", premiumPct: 8}`
   idempotency_key: `inv_20260821_dom014_escalate`

7. **Seasonal overstock reduction**
   summary: "Reduce next reorderQuantity for fresh basil by 40%"
   rationale: "currentStock + reservedStock exceeds 6-week rolling demand by wide margin; local growing season winding down, next batch pricier off-season import. Reducing next PO to avoid waste write-off; does not touch current stock."
   payload: `{itemCode: "ING-BASIL-FRESH", currentReorderQuantity: 40, proposedReorderQuantity: 24}`
   idempotency_key: `inv_20260819_dom014_seasonal_trim`

---

## churn-prevention (2)

8. **Win-back wave, lapsed high-LTV — GDPR-scoped**
   summary: "Send win-back offer to 12 lapsed high-value customers"
   rationale: "No order in 45+ days; orderStats.lifetimeValue in top quartile for this store. Draft offer: 15% off next order, 7-day expiry. Consent check: only customers with active marketingConsent (GDPR Art. 6(1)(a)) included in this batch — 3 otherwise-eligible customers excluded for lacking current consent, logged separately, not contacted."
   payload: `{customerCount: 12, excludedForConsent: 3, offerPct: 15, expiryDays: 7, segment: "lapsed_high_ltv"}`
   idempotency_key: `churn_20260820_dom014_wave3`

9. **Loyalty tier at-risk nudge**
   summary: "Notify 6 customers their loyaltyInfo tier drops in 5 days without an order"
   rationale: "loyaltyInfo.tier recalculates on a rolling 90-day window; these 6 sit within 1 order of dropping from Gold to Silver. Retention nudge, not a discount — informational message only, no monetary payload, transactional not marketing so no separate consent gate applies."
   payload: `{customerCount: 6, tierAtRisk: "GOLD", daysRemaining: 5}`
   idempotency_key: `churn_20260822_dom014_tier_nudge`

---

## review-response (3)

10. **Standard low-rating draft**
    summary: "Draft response to new 2★ review — cold food complaint"
    rationale: "Review flags 'pizza arrived cold', order #ORD-DOM014-88231 delivery time was 47min vs. store avg 28min. Draft acknowledges delay, offers store credit, does not admit systemic fault pending logistics review."
    payload: `{reviewId: "rev_8841", orderId: "ORD-DOM014-88231", draftTone: "apologetic_factual"}`
    idempotency_key: `rev_20260820_dom014_8841`

11. **Escalation-required review (not auto-drafted)**
    summary: "Flag 1★ review alleging foreign object in food for manager, no auto-draft"
    rationale: "Health/safety allegation — outside review-response agent's PROPOSE tier per policy.py; agent explicitly declines to draft language and routes directly to manager + food-safety checklist trigger, consistent with EU food-safety incident handling norms."
    payload: `{reviewId: "rev_8850", escalationReason: "food_safety_allegation", autoDraftSuppressed: true}`
    idempotency_key: `rev_20260821_dom014_8850`

12. **Positive review, low-priority queue**
    summary: "Draft thank-you response to 5★ review mentioning staff by name"
    rationale: "Low urgency; queued behind PROPOSE-tier items. Personalizes response using staff first name only (no surname, no other identifying detail) to reinforce service culture while minimizing personal data exposure in a public reply."
    payload: `{reviewId: "rev_8855", mentionsStaff: "Arjun R."}`
    idempotency_key: `rev_20260822_dom014_8855`

---

## shift-optimisation (2)

13. **Peak-season understaffing risk**
    summary: "Recommend adding 1 kitchen shift, Sat 18:00–22:00"
    rationale: "Order volume forecast (from demand-forecast agent output) exceeds current scheduled kitchen capacity by ~18% in that window for the third consecutive week, tourist-season pattern. Cross-referenced against demand-forecast's weighted moving average, not independently modeled."
    payload: `{shiftDate: "2026-08-22", window: "18:00-22:00", role: "kitchen", recommendedHeadcount: 1}`
    idempotency_key: `shift_20260817_dom014_sat_kitchen`

14. **Overstaffing flagged, cost-saving**
    summary: "Recommend cutting 1 front-of-house shift, Tue 14:00–17:00"
    rationale: "Lowest-volume window in the store's weekly pattern; 3 FOH staff currently scheduled against a historical need of 1.4. No customer-facing risk identified. Recommendation only — does not touch any individual's contracted hours without manager review, per EU working-time notice norms."
    payload: `{shiftDate: "2026-08-18", window: "14:00-17:00", role: "front_of_house", recommendedReduction: 1}`
    idempotency_key: `shift_20260817_dom014_tue_foh`

---

## kitchen-coach (2)

15. **Prep-time drift alert**
    summary: "Flag pizza station prep time drifting 22% above target"
    rationale: "preparationTime on completed orders for PIZZA category items trending up over 9 days. Reported as an aggregate station metric only — no individual staff member is named or scored in the payload, by design, to keep this a process signal rather than personnel evaluation data."
    payload: `{category: "PIZZA", targetPrepMinutes: 11, observedAvgMinutes: 13.4}`
    idempotency_key: `coach_20260820_dom014_pizza_drift`

16. **Portion consistency flag**
    summary: "Flag portionUnit variance on Family Meal Combo above tolerance"
    rationale: "standardPortionSize variance across 14 recent orders of this item exceeds the 8% tolerance band; recommend a manager spot-check, not an automated correction."
    payload: `{menuItemId: "mi_family_combo", toleranceBandPct: 8, observedVariancePct: 13}`
    idempotency_key: `coach_20260821_dom014_portion`

---

## demand-forecast (2, mostly auto/COMPUTE — included to show the READ/COMPUTE tier alongside PROPOSE)

17. **Nightly forecast run, no proposal generated**
    summary: "Nightly forecast completed — 214 item/hour/dow cells updated"
    rationale: "Routine COMPUTE-tier run, auto-resolved, no manager action required. Logged for audit continuity."
    risk: COMPUTE (not PROPOSE — shown in audit trail, not the approval queue)
    idempotency_key: `demand_20260820_dom014_nightly`

18. **Forecast anomaly, escalated to inventory-reorder**
    summary: "Forecast flags 3x normal demand for iced beverages, heatwave forecast"
    rationale: "COLD_DRINKS category demand model shows 3.1x normal Thu-Fri volume given 39°C forecast (Lisbon summer heatwave); this triggered the inventory-reorder agent's proposal-style escalation for backup ice/syrup stock (see inventory-reorder proposal #6 pattern). Demand-forecast itself does not draft POs."
    risk: COMPUTE, with downstream PROPOSE handoff noted
    idempotency_key: `demand_20260821_dom014_heatwave_flag`

---

## Note on EU AI Act framing

Proposals #4, #8, #11, #15 are written to double as concrete illustrations for the submission narrative's compliance angle:
- **#4** — an agent explicitly declining to act and explaining why (transparency of automated reasoning, not just its outputs)
- **#8** — consent-scoped targeting with the exclusion count surfaced, not hidden (data minimization + lawful-basis visibility)
- **#11** — a hard-coded refusal to auto-act on a safety-class input, routed to a human (the policy.py risk-tier boundary made visible)
- **#15** — a design choice to report aggregate signals, not individual-level scoring (avoiding inadvertent workplace-surveillance/profiling characterization)

These four are the ones worth highlighting on camera if the demo video leans into the EU AI Act / governance narrative rather than just the KYA framing.

## Verified drift vs. masova-support's backend_contracts.py fixtures

Confirmed against the real platform entities in `shared-models`, `commerce-service`, `logistics-service`, `payment-service` (design intent noted where drift is deliberate migration-in-progress, not a bug):

- `OrderItem.price`, not `unitPrice` — masova-support's `SAMPLE_ORDER` fixture uses the wrong field name
- `RefundStatus` has no `APPROVED` value — real enum: `PENDING_APPROVAL, INITIATED, PROCESSING, PROCESSED, FAILED, REJECTED`. Approval flows directly into `INITIATED`; there is deliberately no separate approved resting state. masova-support's fixture invents an `APPROVED` value that doesn't exist.
- `Refund` has no `refundId`/`requiresApproval` fields — real: `razorpayRefundId`, no boolean flag
- `Customer.loyaltyInfo` and `Customer.orderStats` are nested objects, not flat scalars (`loyaltyPoints`, `totalOrders`) as masova-support's fixture assumes
- `InventoryItem.itemName` and `.minimumStock`, not `name`/`reorderLevel`
- `Store.id` (Mongo ObjectId) and `Store.code` (human-facing "DOM001"-style) are deliberately distinct fields — masova-support's fixtures conflate them
- `Customer.storeId` is `@Deprecated` in the real entity, superseded by `storeIds` (multi-store) — a genuine, code-documented migration in progress, not something to silently trust either shape of
- `PurchaseOrder.status` is a raw `String`, not an enum, unlike `Order`/`Refund` — likely tech debt, not intent
- masova-support's `PENDING` order-status dual-tolerance has no supporting evidence in the real backend — no `OrderStatus.PENDING` value exists anywhere in the platform's active code; treat as speculative, not confirmed legacy drift
