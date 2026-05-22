# `/my-charges` component split + unified QRPayment active-state classifier

Status: ready-for-agent

## Parent

`.scratch/active-session-on-my-charges/PRD.md`

## What to build

Two structural cleanups that don't affect runtime behavior but make future contributors' lives easier.

1. **Split `app/my-charges/page.tsx`.** The file is now ~900 lines with four embedded components, six helpers, and the main page component. Extract into `app/my-charges/_components/`:
   - `ActiveSessionCard.tsx` (+ `SUB_STATE_META`, `useElapsedSince` → or move `useElapsedSince` to a shared hook file)
   - `RefundLifecycle.tsx` (+ `formatRefundDate`)
   - `TransactionCard.tsx`
   - `ChargerRow.tsx`
   - Leave the page composition + state hooks in `page.tsx`.

2. **Unified QRPayment active-state classifier.** Today three places reason about "is this QR session active?":
   - `QRPaymentService.process_qr_session_billing` (filters by status to decide whether to bill)
   - The stale-payment watchdog (filters by status + age)
   - The new `_classify_sub_state` in `public_qr_active_sessions.py`
   
   Each has subtly different code paths. Consolidate the customer-facing sub-state machine into a single helper — either a `classmethod` on `QRPayment` (e.g. `QRPayment.customer_sub_state(self, transaction=None) -> str | None`) or a free function in a `services/qr_session_state.py` module. The endpoint imports and uses this; the watchdog and billing service migrate to it where their checks overlap (lower-priority cleanup; don't rewrite their state machines in this slice — just make the endpoint use the unified one and add docstrings on the other two pointing at it).

## Acceptance criteria

- [ ] No behavior change visible from the frontend. All existing tests still pass.
- [ ] `app/my-charges/page.tsx` is < 400 lines.
- [ ] The four extracted components have their own files with named exports.
- [ ] `_classify_sub_state` is replaced by a call to the canonical helper. The helper has its own unit tests (move the classifier-pure tests from `tests/test_public_qr_active_sessions.py` to a new `tests/test_qr_session_state.py`).
- [ ] Frontend production build green.

## Blocked by

None — can run in parallel with anything else.
