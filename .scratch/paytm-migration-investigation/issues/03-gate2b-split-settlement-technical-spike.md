# 03 — Gate 2b: Paytm Split Settlement technical spike

Status: ready-for-agent

## What to build

Prove the Paytm Split Settlement product technically covers our franchisee-payout flow, in sandbox. Only worth doing once Gate 1 looks like a pass and Gate 2a confirms the product is available.

- Create vendor / child accounts and complete their onboarding + KYC (penny-drop) via whatever mechanism Gate 2a establishes (API or dashboard).
- Split a payment across parent + vendor accounts (platform-collects-first), then **split a refund back** across those accounts (`splitRefundInfo`, AMOUNT/PERCENTAGE) — confirming it maps to our LIFO-across-payments refund model.
- Allocate commission/fees to vendor accounts via `feePercentage`.
- Map Paytm's settlement states to our `settlement_status` lifecycle (`PENDING → TRANSFER_INITIATED → TRANSFER_PROCESSED → SETTLED` + FAILED/REVERSED/ON_HOLD/BELOW_THRESHOLD).
- Note any gaps vs Razorpay Route (esp. TDS, per Gate 2a).
- Throwaway spike; sandbox only; not wired into production settlement code.

## Acceptance criteria

- [ ] Vendor accounts created and a split payment executed in sandbox
- [ ] A split refund across vendor accounts demonstrated
- [ ] Commission/fee allocation via `feePercentage` demonstrated
- [ ] Paytm settlement states mapped to our `settlement_status` lifecycle, with gaps documented
- [ ] Written verdict on whether Split Settlement covers our franchisee-payout needs
- [ ] Spike code isolated and disposable

## Blocked by

- 01 — Gate 1: Instant-refund reliability spike
- 02 — Gate 2a: Paytm split-settlement commercial + compliance confirmation
