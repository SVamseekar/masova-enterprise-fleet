# MaSoVa Operations Manual — Supplier SLAs (Paris fleet)

**Document ID:** MOS-SU-001  
**Owner:** Supply and Procurement  
**Applies to:** Dry, chilled, produce, and packaging suppliers serving MaSoVa Paris stores  
**Audience:** Store managers, inventory leads, procurement  
**Related:** MOS-FS-001 (receiving temperatures); Inventory Reorder agent (draft POs only)

Live on-hand quantities, reorder points, and purchase-order lines come from inventory tools and the system of record. **This manual is not a stock list.** Agents must not treat paragraphs here as order quantities.

---

## 1. Delivery windows

Chilled lines target **morning windows** so coolers restock before lunch. Each store’s contracted window is on the vendor card in procurement.

- Arrival after the SLA **grace period** (typically 30 minutes past the window unless the contract says otherwise) is logged as late.
- Managers record a PO note and, if service is at risk, open a claim. They do **not** auto-inflate the next order quantity to “catch up” without a reviewed draft PO.
- Dry and packaging may use a later window; they still cannot block the chilled dock.

---

## 2. Fill rate and substitutions

Preferred fill rate: **95% or more** of ordered lines by SKU, not by weight substitution.

Substitutions that change:

- Allergen profile (see MOS-FS-001)
- Dough specification or hydration
- Mozzarella / tomato brand used in the standard recipe

require **manager OK** before the line is accepted. Rejected lines get a reason code for the weekly vendor review (short, damaged, wrong spec, temperature fail).

The Inventory Reorder agent drafts a PO using **reorder_quantity** and contracted pack sizes. It must not invent a “covers the forecast” quantity that ignores the SLA pack.

---

## 3. Temperature on arrival

Chilled goods must arrive within HACCP cooler ranges (**0–4 °C** product surface). Reject warm dairy or protein. Photograph the probe reading for the claim file. Do not “receive then sort later” on a failed probe.

Frozen: **−18 °C** or colder at surface. Soft boxes are a reject.

---

## 4. Pricing, invoices, and payment

Contracted rates are in procurement. Flag invoice variance vs contracted rate within **five business days**.

The Manager Copilot and ops agents **do not approve supplier payment**, do not promise a new rate, and do not settle disputes in chat. Finance owns settlement.

---

## 5. Claims and credits

| Event | Store action | Procurement |
|-------|----------------|-------------|
| Late beyond grace | Log + PO note | Vendor scorecard |
| Short / damaged | Reason code + photo | Credit request |
| Temperature fail | Reject + photo | Claim; do not use product |
| Repeat fails (3 in 30 days) | Escalate | Source review |

---

## 6. What the Inventory Reorder agent may do

| Allowed | Not allowed |
|---------|-------------|
| Read on-hand, reorder point, supplier, pack size | Send the PO to the vendor |
| Draft a PO at reorder_quantity | Change contracted price |
| Notify managers | Accept a substitution |

Approve / reject remains a human action in the console. After approve, demo or platform apply follows the HITL path — never a silent vendor call from the model.
