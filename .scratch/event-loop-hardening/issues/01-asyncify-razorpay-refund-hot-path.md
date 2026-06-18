Status: done

# Async-ify Razorpay refund_payment + find_refund_for_payment (hot path)

## Context

During the 2026-06-01 staging incident, the backend event loop wedged for 100–190 seconds at a time. Logs ruled out DB / Redis / network as causes (DB CPU 4–9%, only 5 connections, backend process state=S, 0.17% CPU). The strongest mechanical hypothesis is that `razorpay_service` has ~18 sync methods that use the official `razorpay` Python SDK (which calls `requests` under the hood). Each sync HTTP call blocks the asyncio event loop for the full Razorpay round-trip.

The codebase **already established the migration pattern**: `razorpay_service.create_payment_transfer` (line 881 of `backend/services/razorpay_service.py`) was rewritten to use `httpx.AsyncClient` for exactly this reason. The inline comment on that method says:

> httpx.AsyncClient — non-blocking; the previous sync `requests` call stalled the event loop for the full Razorpay round-trip (up to 30s), serialising every other concurrent task.

The migration was not completed across the remaining sync methods. This issue covers the **hot path**: refunds. Refunds fire on every QR session end (normal completion via `process_qr_session_billing`, charging-failed via `_full_refund` / `handle_charging_failure`, and the 30-minute periodic billing retry). These are the most frequently-fired sync HTTP calls in the system.

## What to build

Convert `razorpay_service.refund_payment` and `razorpay_service.find_refund_for_payment` from sync (`def`) to async (`async def`) using `httpx.AsyncClient` with `timeout=10`. Update all call sites to `await` them. Preserve the existing exception-translation behavior (`RazorpayAlreadyRefundedError`, `RazorpayRefundBelowMinimumError`) by matching on the parsed JSON error description, the same way `create_payment_transfer` handles error mapping.

The Razorpay refund endpoint is `POST /v1/payments/{payment_id}/refunds`. The find-refund endpoint composes two calls (`GET /v1/payments/{id}` then `GET /v1/payments/{id}/refunds`); both need to be async.

Use the existing `create_payment_transfer` (line 881) as the structural template — same auth tuple, same `X-Refund-Idempotency` header injection, same response-shape preservation, same `httpx.AsyncClient` setup.

## What to change

- `backend/services/razorpay_service.py:449` — convert `def refund_payment` to `async def refund_payment` using `httpx.AsyncClient`. Drop the `self.client.payment.refund(...)` SDK call. Preserve all kwargs (`amount`, `notes`, `idempotency_key`, `speed`) and the error-mapping branches at the bottom (`_is_already_refunded_error`, `_is_amount_below_minimum_error`) — match on the parsed JSON error description string instead of SDK exception types.
- `backend/services/razorpay_service.py:519` — convert `def find_refund_for_payment` to `async def find_refund_for_payment` using `httpx.AsyncClient`. Two sequential awaits.
- `backend/services/qr_payment_service.py:820` — change `razorpay_service.refund_payment(...)` to `await razorpay_service.refund_payment(...)` inside `process_qr_session_billing`.
- `backend/services/qr_payment_service.py:925` — same change inside `_full_refund` (or wherever the line resolves to — confirm by reading the function it sits in).
- `backend/services/qr_payment_service.py:947` — change `razorpay_service.find_refund_for_payment(...)` to `await razorpay_service.find_refund_for_payment(...)`.
- `backend/services/billing_retry_service.py:136` — change `razorpay_service.refund_payment(...)` to `await razorpay_service.refund_payment(...)`.

Confirm there are no other callers via `grep -rn "razorpay_service\.refund_payment\|razorpay_service\.find_refund_for_payment" backend/` before declaring done.

## Acceptance criteria

- [ ] Both methods on `RazorpayService` are `async def` and use `httpx.AsyncClient` with `timeout=10`.
- [ ] `RazorpayAlreadyRefundedError` and `RazorpayRefundBelowMinimumError` still raise correctly when Razorpay returns the corresponding errors (covered by existing tests; add fixtures if missing).
- [ ] `X-Refund-Idempotency` header is sent when `idempotency_key` is provided.
- [ ] All 4 call sites are updated to `await` the methods.
- [ ] No remaining `razorpay_service.refund_payment(` or `razorpay_service.find_refund_for_payment(` without `await` in the codebase.
- [ ] Existing tests in `backend/tests/` covering refund flows pass via `docker exec ocpp-backend pytest` (filter to refund-related tests).
- [ ] Manual sanity: trigger a QR session end on staging with the new build; verify the refund completes; verify backend stays responsive (no freeze window around the refund).
- [ ] Resolves the freeze hypothesis from Sentry issues `OCPP-BACKEND-K` (Cannot call "send" once a close message has been sent) and `OCPP-BACKEND-V` (Unexpected ASGI message 'websocket.send') — these should stop accumulating once event-loop blocking on refund calls is removed.

## Blocked by

None — can start immediately. Independent of all other event-loop-hardening issues.
