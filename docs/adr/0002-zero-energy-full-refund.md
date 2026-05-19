# A zero-energy QR session issues a full refund and no GST invoice

When a QR-funded charging session ends with `energy_consumed_kwh ≤ 0` (charger reports zero meter delivery), the customer is refunded the entire `amount_paid` — not `amount_paid - platform_fee` as previously. No GST invoice is issued, since no taxable supply occurred. Razorpay's actual processing fee on the original capture is still recorded on the `QRPayment` row for reconciliation, but VoltLync absorbs it (and any refund-processing fee) as P&L loss.

Rationale: a customer who paid and received nothing should be made whole. Deducting the gateway fee against a non-delivery is bad CX, treats the failure mode as if it were partial delivery (which it isn't), and the negative-NPS / social-media risk of "they kept ₹10 for nothing" costs more than the absorbed fee.

## Considered alternatives

- **Keep deducting the gateway fee** (the pre-ADR behavior). Rejected: cost-recovery on failed service is the kind of policy customers screenshot and tweet about.
- **Issue a zero-value GST invoice** for audit-trail completeness. Rejected: invalid under CGST Rule 46 (no taxable value), and the `QRPayment` row already provides the audit trail.

## Consequences

- A future contributor looking at `_full_refund` will see the actual platform fee captured on the row but ignored in the refund formula — this is intentional; see also ADR 0001.
- The "energy=0 absorbed loss" is queryable as `SUM(QRPayment.platform_fee WHERE refund_amount = amount_paid AND energy_consumed_kwh = 0)`.
