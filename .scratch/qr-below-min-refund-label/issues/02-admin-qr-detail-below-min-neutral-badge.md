# Admin QR detail: neutral badge for below-minimum (not red "REFUND_FAILED")

Status: done

## What to build

On the admin `qr-codes/[id]` payments table, a `REFUND_FAILED` row is rendered with the red `destructive` badge variant. For the **below-Razorpay-minimum** case (`failure_reason = "below_razorpay_minimum"`, a benign sub-₹1 forfeit, already excluded from retries) this falsely signals an operational problem and inflates the apparent REFUND_FAILED count ops has to triage.

Render a below-minimum payment with a **neutral** badge (not `destructive`) and a short "below ₹1, not refundable" hint, so the genuinely-failed refunds stand out from the benign sub-rupee ones.

End-to-end:
- **Backend:** expose the same `refund_below_minimum` signal (introduced in slice 01) on the admin QR-payments payload.
- **Frontend:** the admin badge map renders below-minimum as neutral/secondary (with hint text); any other `REFUND_FAILED` reason keeps the red `destructive` treatment.

Display-layer only — **no status enum change, no migration.** Reuses slice 01's robust below-minimum classification (canonical marker + legacy long-form) — do not reimplement the detection.

## Acceptance criteria

- [ ] Admin QR-payments payload carries the below-minimum signal (reusing slice 01's derived flag/helper, not a duplicate predicate)
- [ ] On the admin QR detail page, a below-minimum payment shows a neutral badge + "below ₹1, not refundable" hint
- [ ] A genuine `REFUND_FAILED` (any other reason) still shows the red `destructive` badge
- [ ] `docker exec ocpp-backend pytest` green for affected tests; `cd frontend && npm run build` passes

## Blocked by

- 01-customer-receipt-below-min-not-failed (introduces the shared below-minimum classification this slice reuses)

## Comments

**2026-06-11 — implemented (local; not committed/deployed).**

- **Backend:** the admin `GET /qr-codes/{id}/payments` payload now carries `refund_below_minimum`, computed with the **shared `is_below_minimum_reason` helper from slice 01** (no duplicate predicate) — `status==REFUND_FAILED and is_below_minimum_reason(failure_reason)`.
- **Frontend (`admin/qr-codes/[id]`):** `getStatusBadge` takes a `belowMinimum` flag; a below-min row renders a neutral **`secondary`** badge labelled **"No refund · below ₹1"** instead of the red `destructive` "REFUND_FAILED". Any other REFUND_FAILED reason keeps the red badge. `refund_below_minimum?: boolean` added to the `QRPayment` type in `types/api.ts`.
- **Tests:** added an endpoint test to `test_admin_qr_codes.py` asserting `refund_below_minimum` is true for a below-min row, false for a genuine REFUND_FAILED, and false for COMPLETED. `docker exec ocpp-backend pytest tests/test_admin_qr_codes.py` → 5 passed; `cd frontend && npm run build` passes.
