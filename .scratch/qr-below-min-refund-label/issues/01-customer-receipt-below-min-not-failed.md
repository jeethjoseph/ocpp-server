# Customer receipt: stop showing a sub-₹1 forfeit as "Refund Failed"

Status: done

## What to build

When a **QR Session** bills almost the entire prepaid amount and leaves an unused balance **below Razorpay's ₹1.00 minimum**, the payment is parked in `REFUND_FAILED` with `failure_reason = "below_razorpay_minimum"`. This is a benign terminal state (Razorpay physically cannot process a sub-₹1 refund; it's correctly excluded from the billing-retry sweep) — but the customer-facing `my-charges` view renders it as a red **"Refund Failed"** error. Example: payment paid ₹20, consumed ₹19.98 of energy+GST+fee, ₹0.02 unrefundable → customer sees "Refund Failed" on their own receipt.

Make a below-minimum payment render as a **neutral/benign** state on the customer view instead of an error — e.g. "Completed · ₹0.02 not refundable (below ₹1)" (wording adjustable in review).

End-to-end:
- **Backend:** introduce a single derived classification — a `refund_below_minimum` boolean (or equivalent) computed with the **same robust below-minimum detection used by `is_retryable_refund_failure`** (must match both the canonical `below_razorpay_minimum` marker AND the legacy long-form "...below Razorpay minimum (₹1.00)..." text). Surface it on the public QR-transactions payload. NB: today the marker lives in the `failure_reason` column, but the public endpoint only exposes `refund_failure_reason`, so the frontend currently cannot distinguish below-min from a genuine failure — closing that gap is part of this slice.
- **Frontend:** the transaction card and the status-filter option treat a below-minimum payment as neutral/success styling + copy, not the red failure treatment. Genuine `REFUND_FAILED` (any other reason) is unchanged.

This is display-layer only — **no status enum change, no migration.** The internal status stays `REFUND_FAILED`.

## Acceptance criteria

- [ ] Public QR-transactions payload carries a below-minimum signal the frontend can read (derived from the robust below-min predicate, covering canonical + legacy long-form reasons)
- [ ] On `my-charges`, a below-minimum payment renders as neutral/benign (no red "Refund Failed"), with copy conveying the sub-₹1 balance is not refundable
- [ ] A genuine `REFUND_FAILED` (e.g. a real Razorpay/network error) still renders as a failure — the relabel is scoped strictly to the below-minimum case
- [ ] The status-filter label no longer presents below-minimum rows as "Refund Failed"
- [ ] Backend test: the below-minimum flag is true for canonical + legacy long-form reasons and false for genuine failures / non-failed statuses
- [ ] `docker exec ocpp-backend pytest` green for affected tests; `cd frontend && npm run build` passes

## Blocked by

- None - can start immediately

## Comments

**2026-06-11 — implemented (local; not committed/deployed).**

- **Backend:** extracted `is_below_minimum_reason(failure_reason)` in `qr_payment_service.py` (canonical marker + legacy long-form, substring-robust) and refactored `is_retryable_refund_failure` to reuse it (single source of truth). The public QR-transactions payload now carries `refund_below_minimum = (status==REFUND_FAILED and is_below_minimum_reason(failure_reason))`.
- **Frontend (`my-charges`):** added `refund_below_minimum` to `QRTransactionItem`. `TransactionCard` renders a below-min row as a green **"Completed"** badge (not red "REFUND FAILED"), suppresses the red raw-reason alert, and enables the GST-invoice download (service was rendered). `RefundLifecycle` shows a calm muted note ("₹0.02 unused — below Razorpay's ₹1 minimum, so it can't be refunded.") instead of the misleading purple "Refund initiated · awaiting confirmation" (which `refund_amount` being set would otherwise trigger).
- **Tests:** `is_below_minimum_reason` parametrized unit table (in `test_qr_payment_service.py`) + new `test_public_qr_transactions.py` asserting `refund_below_minimum` is true for below-min, false for a genuine REFUND_FAILED and for COMPLETED. `docker exec ocpp-backend pytest` → 79 passed; `cd frontend && npm run build` passes.

**Note on the status filter:** left as-is. The dropdown still filters by the `REFUND_FAILED` enum (below-min rows are that status internally); the per-row card now displays them benignly, which is the user-visible fix. A separate "below-minimum" filter facet wasn't added (out of scope).

**Slice 02 is now unblocked** — `is_below_minimum_reason` and the `refund_below_minimum` payload pattern exist for the admin endpoint to reuse.
