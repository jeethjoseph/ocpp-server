# 03 — LIFO refund of unused budget at StopTransaction

Status: ready-for-agent

## What to build

At session end, return the unused budget of a stacked QR Session across its payments using **LIFO** allocation, per ADR 0021.

At StopTransaction, compute `remainder = Σ prepaid − actual cost` (energy + GST + fees) and refund it **most-recent payment first**, walking backward. Each linked payment ends up fully consumed (no refund), fully unused (full refund), or — for at most one boundary payment — partially refunded. One GST invoice covers the session's total delivered energy (the taxable event is energy delivery, not payment).

This also absorbs the stop-race case from ADR 0021: a top-up that landed just as the session stopped becomes unused budget and is simply refunded — no special-casing.

## Acceptance criteria

- [ ] Unused remainder is refunded LIFO (most recent payment first) across linked payments
- [ ] Fully-consumed payments get no refund; fully-unused get full refund; at most one payment is partially refunded
- [ ] `cost ≥ Σ prepaid` (budget overshoot) results in zero refund, no error
- [ ] Existing zero-energy / fault-refund full-refund bands still refund all payments fully
- [ ] One GST invoice per session for total delivered energy
- [ ] Refunds reuse the per-payment refund path and `qr_payment_{PK}` idempotency key
- [ ] Per-file pytest: multi-payment LIFO split, boundary partial, overshoot=zero, full-refund band

## Blocked by

- 01 — Same-payer top-up replaces reject-when-busy (summed budget)
