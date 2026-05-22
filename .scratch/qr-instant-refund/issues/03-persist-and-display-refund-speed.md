Status: ready-for-agent

# Persist Razorpay refund speed_processed and surface in admin UI

## Parent

`.scratch/qr-instant-refund/issues/01-instant-refund-for-full-refunds.md`

## What to build

Issue 01 made every `_full_refund` request Razorpay's `speed=optimum` mode, but the actual outcome (`speed_processed = "instant"` vs `"normal"`) currently lives only in a log line emitted by `RazorpayService.refund_payment`. Ops cannot tell from the admin UI whether a specific customer's refund was processed instantly or fell back to the normal 5–7 day rail — they have to grep backend logs or open the Razorpay dashboard.

This slice persists the outcome on the `QRPayment` row (single nullable column — metadata about an existing refund, not a parallel tracking entity) and surfaces it as a small badge on the admin QR detail page.

### Backend

- Aerich migration: add `QRPayment.razorpay_refund_speed_processed VARCHAR(20) NULL`. Backward-compatible (NULL for all pre-feature refunds and for partial refunds, which stay on normal speed).
- `models.py`: declare the field on the `QRPayment` Tortoise model.
- `services/qr_payment_service.py._full_refund`: after `razorpay_service.refund_payment` returns, read `refund_result.get("speed_processed")` and assign to `locked.razorpay_refund_speed_processed` before the existing `await locked.save()`. Also write the value on the already-refunded reconciliation path (`RazorpayAlreadyRefundedError` → `find_refund_for_payment`) when the existing-refund dict carries a `speed_processed` field.
- Admin QR detail endpoint (`routers/qr_codes.py` — the GET /api/admin/qr-codes/{id}/payments-style endpoint, or wherever the admin payment list is served): include `razorpay_refund_speed_processed` in the response payload.

### Frontend

- `app/admin/qr-codes/[id]/page.tsx` (admin QR detail page, `PaymentQRCard` or equivalent): render a small badge next to the refund amount when `razorpay_refund_speed_processed` is non-null:
  - `Instant ⚡` (green) when value is `"instant"`
  - `Normal (5–7 days)` (gray) when value is `"normal"` or any other non-null value
  - Render nothing when the field is null (covers all pre-feature refunds + partial refunds)
- Admin-only. `/my-charges` (customer-facing) is unchanged.
- Use existing badge/chip components from the shadcn/ui design system. Do not introduce new color tokens.

### Tests

- Backend: extend a `_full_refund` test to mock the Razorpay response with `speed_processed: "instant"` and assert the column gets persisted; another test with `speed_processed: "normal"` to confirm fallback persistence.
- Backend: assert the admin payment endpoint returns the field.
- Frontend: `cd frontend && npm run build` passes (CLAUDE.md mandates the full production build, not just `tsc`).

## Acceptance criteria

- [ ] New Aerich migration creates `qr_payment.razorpay_refund_speed_processed` (nullable VARCHAR(20)).
- [ ] `QRPayment.razorpay_refund_speed_processed` is populated on every `_full_refund` invocation (both happy path and `RazorpayAlreadyRefundedError` reconciliation when the existing-refund dict provides it).
- [ ] Admin QR detail API returns `razorpay_refund_speed_processed` on the relevant payment row.
- [ ] Admin QR detail page displays an `Instant ⚡` (green) or `Normal (5–7 days)` (gray) badge next to the refund amount when the field is non-null; renders nothing when null.
- [ ] Customer-facing `/my-charges` page is untouched.
- [ ] Existing tests still pass; new tests added per the description.
- [ ] `cd frontend && npm run build` passes.
- [ ] Migration generated via Aerich, not hand-written (per CLAUDE.md).

## Blocked by

None - can start immediately.

## Comments

### Files changed
- `backend/models.py` — added `QRPayment.razorpay_refund_speed_processed` field.
- `backend/migrations/models/40_20260520075333_add_refund_speed_processed.py` — Aerich-generated migration (clean single-statement ALTER, no snapshot drift).
- `backend/services/qr_payment_service.py._full_refund` — persist `speed_processed` from both the happy path (`refund_result.get("speed_processed")`) and the reconciliation path (`existing.get("speed_processed")`).
- `backend/routers/qr_codes.py` — admin `/api/admin/qr-codes/{id}/payments` endpoint now returns `razorpay_refund_speed_processed`.
- `frontend/types/api.ts` — added `razorpay_refund_speed_processed?: string | null` to `QRPayment` interface.
- `frontend/app/admin/qr-codes/[id]/page.tsx` — added `getRefundSpeedBadge()` helper, rendered next to the refund amount cell. `Instant` uses an existing tailwind green pattern (matches `chargers/[id]/page.tsx`); `Normal (5-7 days)` uses the shadcn `secondary` variant.

### Tests added/modified
- Updated `test_full_refund_passes_speed_optimum_when_flag_enabled` to also assert `qr_payment.razorpay_refund_speed_processed == "instant"` after the call (so the column-write is covered without adding a duplicate test).
- Added `test_full_refund_persists_speed_processed_normal_on_fallback` — covers the Razorpay-side instant→normal fallback.
- Added `test_full_refund_persists_speed_processed_from_reconciliation` — covers the `RazorpayAlreadyRefundedError` → `find_refund_for_payment` path.
- Added `test_admin_qr_payments_endpoint_returns_refund_speed_processed` — hits the actual admin endpoint via `client_admin` to verify the field surfaces in the response.

### Judgment calls
- Migration generated cleanly via `aerich migrate --name add_refund_speed_processed` (40_20260520075333). One-line ALTER. No staleness or snapshot poisoning observed.
- Badge text uses a regular hyphen (`Normal (5-7 days)`) not an em-dash because Next/ESLint `react/no-unescaped-entities` rejects raw em-dashes in JSX without escaping.
- Used the same tailwind green utilities already in use elsewhere (`bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-400`) instead of inventing a new variant on the Badge component — keeps the design system surface unchanged.

### Build verification
- `docker exec ocpp-backend pytest tests/test_qr_payment_service.py` → 35 passed.
- `cd frontend && npm run build` → passed (no new warnings; `/admin/qr-codes/[id]` route compiled to 6.87 kB).
