# 04 — Customer-facing "pay again to charge longer" hint

Status: ready-for-agent

## What to build

Tell the customer they can extend an active QR Session by paying again. Optional UX polish on the public QR / active-session surface — pure frontend, no billing logic.

On the public active-session view for a CHARGING QR Session, surface a hint (and, where feasible, a re-scan/pay affordance) explaining that another payment from the same payer extends the current charge rather than starting a new session. Copy should make the **same-payer** condition clear so a customer isn't surprised when a mismatched payer is refunded instead.

## Acceptance criteria

- [ ] Active QR Session view shows a clear "pay again to charge longer" hint
- [ ] Copy communicates that the top-up must come from the same payer (VPA/phone)
- [ ] No change to billing, budget, or refund logic — presentation only
- [ ] `cd frontend && npm run build` passes

## Blocked by

- 01 — Same-payer top-up replaces reject-when-busy (summed budget)
