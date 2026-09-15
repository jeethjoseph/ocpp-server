# Franchisee as Billing Entity — Strategy & Feasibility Analysis

**Date:** 2026-07-30 · **Status:** Exploration (no decision taken; ADR to follow if/when the model is adopted)
**Origin:** Finance advisor proposal — make the franchisee the billing entity so sub-GST-threshold franchisees charge no GST; VoltLync invoices the franchisee a commission + 18% GST as a service provider.

---

## 1. The proposal

- Franchisee becomes the supplier/biller of the charging service to the customer.
- Franchisees under the GST registration threshold (₹20L services turnover) charge **no GST** → ~15% consumer price cut or margin lift.
- VoltLync's revenue becomes a B2B service: commission invoiced to the franchisee + 18% GST on the commission only.

## 2. Why the upside is real

- Today VoltLync charges customers 18% GST on energy with almost **no input credit** to offset (franchisees buy electricity from KSEB — exempt supply, no ITC). The 18% is nearly pure deadweight on the consumer.
- VoltLync's own GST surface shrinks to commission-only.
- Strong franchisee recruitment pitch vs networks that bill with 18%.

## 3. The legal reality (verified 2026-07-30)

### Section 9(5) — the "Ola provision" — does NOT apply
- 9(5) CGST: for a **closed, notified list** of services (cab rides, unregistered-host hotels, housekeeping, restaurant delivery), the e-commerce operator pays GST as if it were the supplier; suppliers are exempted from registration.
- **EV charging is not on the list and cannot be opted into.**
- 9(5) *relocates* tax, it doesn't remove it — Ola pays 5% on every ride. If charging were ever notified, VoltLync would pay 18% on full charge value. Opposite of the goal.

### The actual precedent: the Namma Yatri / SaaS structure — contested
- Namma Yatri (Juspay) won a Karnataka AAR ruling (Sept 2023): not liable under 9(5) because it only links parties and **the fare never passes through the platform**.
- Uber and Rapido tried equivalent subscription models and **lost** (Uber: Nov 2024 AAR) — because they control fares, ride management, and the customer relationship.
- The AAR has signalled it may **recall** even the Namma Yatri ruling (Jun 2025); the government is mulling a **CGST amendment** to close the SaaS-vs-commission arbitrage entirely.
- **The dividing line: who touches the money and who sets the price.** VoltLync today collects every payment, sets tariff display, owns the app, handles refunds → currently on the losing (Uber) side of that line, with 18% exposure instead of 5%.

### EV charging industry practice
- 18% GST on charging-as-a-service is settled (Ministry of Power clarification + AAR rulings).
- CPO-merchant networks (Tata Power, Statiq, ChargeZone) bill customers themselves with 18%.
- Host-led models (Bolt.Earth ~63% of public charge points per BEE; Kazam) push billing to the host; many small hosts collect directly via their own UPI and charge no GST. **Nobody credible runs "platform collects the money but the unregistered franchisee is the supplier"** — that hybrid is what the AAR rejected for Uber/Rapido.

### Residual obligations even after a clean flip
Facilitating payment through the platform (even with franchisee as merchant of record) likely still makes VoltLync an **e-commerce operator**: Section 52 TCS and possibly 194-O TDS (1% on gross) attach to VoltLync regardless of who bills. MoR-flip settles *who invoices the customer*, not VoltLync's collection-agent obligations. Both questions go in the CA opinion.

## 4. Strategic counterweight: utilisation, not tax, is today's constraint

From the 2026-07 utilisation report (`.scratch/utilisation-report-2026-07/`): prod averages **1.04 h/day per Socket charger, 0.37 h/day Type2**; three chargers did zero sessions in 30 days; one charger (VOW0007) carries 74% of all hours. Every franchisee is far below ₹20L — the model applies, but 18% of a small number is a small number. Months of restructuring vs demand work is a real trade-off. Corollary: fix the structure **before** volumes are big enough to attract recharacterization attention.

## 5. Payments architecture — how VoltLync takes commission like a PA does

### Route cannot make a linked account the merchant of record
Route's design: platform is the merchant, payments land on the platform MID, linked accounts are settlement destinations. Refunds initiate from the primary account. No configuration inverts this.

Razorpay deducts fees at source because it holds an RBI PA licence. VoltLync must not intercept funds itself (unlicensed aggregation) — the play is to have the licensed PA execute the split.

### Option A — Aggregator Partner + sub-merchant accounts (foundation)
- VoltLync enrolls as Razorpay **Aggregator Partner**; each franchisee onboarded as a **sub-merchant with their own account/MID** via Sub-Merchant Onboarding APIs (KYC completes inside VoltLync's platform).
- Franchisee = merchant of record. VoltLync operates the account with partner credentials (payments, refunds, settlement reads).
- Existing `Franchisee` + `FranchiseeStakeholder` Route-KYC machinery re-points to this with modest changes (same accounts API family).
- Partner-program commission (share of Razorpay's fees when sub-merchants transact on the partner key) offsets gateway costs but is **not** the platform's 20% cut.

### Option B — "Inverse Route" for the commission (the ask)
- Enable Route **on each franchisee's sub-merchant account**, with **VoltLync as the franchisee's linked account**.
- Every captured payment auto-splits at source: commission% → VoltLync, remainder → franchisee. Executed by the licensed PA under a standing instruction in the franchise agreement.
- Backend creates transfers via partner credentials — same API family as today's Route transfers, direction reversed.
- Needs Razorpay partner-team sign-off (Route enablement per sub-merchant is not self-serve). Self-dealing (VoltLync writing its own commission transfers) must be explicitly authorized in the franchise agreement.

### Option C — Fallback: invoice + auto-debit
- Monthly `CommissionInvoice` (commission + 18% GST) collected via eNACH / UPI Autopay mandate set at onboarding.
- Legally boring, PG-agnostic; downside is post-settlement credit exposure + dunning ops.

### Side effects of the sub-merchant topology
- UPI payee name at payment becomes the **franchisee** → strengthens the substance argument and resolves the Route disclosure question.
- Refunds debit the franchisee's own balance → dissolves the staging↔prod refund idempotency-key collision (keys scope per account).
- Webhooks/payment objects become per-sub-merchant (scoped by partner key) → multi-tenant webhook handling required.

## 6. What must change in the product (scoping)

### Wallet — decide first, it's the fork
Platform wallet redeemable across many independent billing entities ≈ semi-closed PPI → RBI licence territory. Options: (a) wallet valid only on `billing_entity=PLATFORM` chargers (natural pilot posture), (b) phase out wallet for QR-only, (c) licensed PPI partner. Check wallet share of revenue before choosing.

### Data model (Aerich)
- `Franchisee`: `billing_entity` mode flag (`PLATFORM` | `FRANCHISEE` — the dual-mode rollout switch), `gst_registered` bool, sub-merchant account fields.
- New FY **turnover tracking** per franchisee (durable counter + alert thresholds for the ₹20L cliff).
- New **`CommissionInvoice`** — commission becomes a real B2B tax invoice from VoltLync (today it's only a deduction inside `CommissionLedgerEntry`), own numbering series.
- `GSTInvoice`: `supplier_*` fields stop being hardcoded VoltLync; add document-type for **bill of supply** (unregistered franchisee — no GST lines). Per-franchisee `GSTInvoiceCounter` infrastructure survives as-is.
- `CommissionLedgerEntry`: `gst_collected`/`net_excl_gst` semantics change per mode; add GST-on-commission columns; revisit TDS columns for 194-O vs 194-H per CA opinion.

### Billing pipeline
- `transaction_finalizer` / `billing_rules`: GST computed via charger → station → franchisee tax profile, not global 18%. Snapshot pattern (`gst_rate_percent` per txn) already handles mid-year registration flips.
- `invoice_service`: three render paths — franchisee tax invoice / bill of supply / legacy VoltLync invoice.
- `franchisee_settlement_service`: direction inverts for franchisee-collected payments (collect commission, don't pay out share); refunds from franchisee account.

### Substance requirements (product changes with legal weight)
- **Franchisee sets the tariff** — moves to franchisee portal; admin becomes approval/guardrails. Non-negotiable for the structure to survive a Namma Yatri-style test.
- Franchisee named as payee at payment and on the invoice.
- Tariff display per charger: "GST included" vs plain rate (`rate_gst_included` meaningless for unregistered franchisees).

### Threshold monitoring
Cron tracking per-franchisee FY turnover; Zulip alerts at ~₹15L/₹18L; documented runbook for the crossing (register → flip `gst_registered` → invoice type + price display change mid-cycle).

### Surfaces
Admin: tax profiles, billing-mode toggle, turnover dashboard, commission invoices. Franchisee portal: tariff setting, own invoices, commission invoices payable. GST filings page: commission-GST only for franchisee-billed volume. Public QR pages: franchisee identity.

### B2B customer impact
Fleet/corporate customers get no input credit from unregistered franchisees. Fine if B2C-only; segment-killer if fleets are on the roadmap.

## 7. Gating sequence

1. **Razorpay partner-team call** — two asks: aggregator enrollment with API onboarding; Route-on-sub-merchant-accounts for at-source commission (Option B). Everything waits on this.
2. **CA/GST written opinion** — ECO status under the new topology; Section 24(ix) registration + exemption-notification applicability for franchisees; TCS §52 and 194-O mechanics with unregistered suppliers; recharacterization risk given platform history of setting prices; which side of the Namma Yatri/Uber line the intended flow falls on. Cheap, and it's the kill-switch.
3. **Wallet decision** (business, needs wallet-vs-QR revenue split).
4. If all clear: schema → pipeline → portal, shipped dark behind `billing_entity`; pilot 2–3 franchisees, QR-only, wallet stays platform-mode.
5. Sequence after (or alongside) utilisation work — the model's value and its scrutiny risk both grow with volume.

**Scope estimate:** billing/invoice layer ≈ weeks (snapshot-based design absorbs it well). Payments topology change (multi-tenant collection, webhooks, refunds) is the long pole.

## 8. Kill criteria

- Razorpay can't/won't do sub-merchant MoR with a workable commission mechanism (A+B and C all fail).
- CA opinion: mandatory registration for franchisees supplying through the platform (threshold premise dead), or recharacterization risk assessed as high.
- CGST amendment lands closing the SaaS/commission arbitrage before pilot.
- Wallet revenue share too high to strand and no acceptable wallet answer.

## Sources

- [ClearTax — Section 9(5) notified services](https://cleartax.in/s/gst-on-notified-services-ecommerce-operators-95)
- [NALSAR CTL — Ola/Uber subscription move](https://ctl.nalsar.ac.in/the-taxi-tax-transition-the-gst-dilemma-behind-ola-and-ubers-subscription-move/)
- [SAG Infotech — Rapido AAR ruling](https://blog.saginfotech.com/karnataka-aar-rules-rapido-pay-gst-cab-service)
- [TaxO — ride apps switch to subscription](https://taxo.online/latest-news/01-03-2025-ride-apps-switch-to-subscription-model-amid-conflicting-rulings-on-gst-liability/)
- [TaxO — AAR may recall Namma Yatri ruling](https://taxo.online/latest-news/28-06-2025-gst-on-ride-hailing-karnataka-aar-says-may-recall-ruling-on-namma-yatri/)
- [A2Z Taxcorp — CGST amendment mulled](https://a2ztaxcorp.net/govt-eyes-amendment-to-cgst-act-to-bring-tax-consistency-for-ride-hailing-firms-say-sources/)
- [ClearTax — GST on EV charging](https://cleartax.in/s/gst-on-ev)
- [CAclubindia — 18% on charging services](https://www.caclubindia.com/articles/gst-implications-for-ev-charging-stations-charging-services-and-taxation-at-18-percent-50065.asp)
- [Razorpay — Route refunds](https://razorpay.com/docs/payments/route/refund/) · [Linked Accounts](https://razorpay.com/docs/payments/route/linked-account/)
- [Razorpay — Aggregator partners](https://razorpay.com/docs/partners/aggregators/) · [Sub-Merchant Onboarding APIs](https://razorpay.com/docs/partners/aggregators/onboarding-api/) · [Partner commissions](https://razorpay.com/docs/partners/commissions/) · [Aggregator T&Cs](https://razorpay.com/s/terms/partners/aggregator-and-platform/)
