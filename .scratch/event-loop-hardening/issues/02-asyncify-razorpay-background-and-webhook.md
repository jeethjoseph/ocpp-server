Status: done

# Async-ify Razorpay create_transfer + fetch_order + fetch_payment + fetch_payment_fees (background & webhook paths)

## Context

See issue 01 for the full background on sync-Razorpay-in-async causing event-loop freezes. The migration template is `razorpay_service.create_payment_transfer` (line 881 of `backend/services/razorpay_service.py`) which uses `httpx.AsyncClient` with `timeout=10`.

This issue covers the **background / webhook** group of sync Razorpay calls — they fire from scheduled services, settlement loops, and webhook handlers. Lower-frequency than refunds (issue 01) but still on the critical async path: a stalled webhook handler delays all subsequent webhook processing, and a stalled settlement loop holds connection-manager state for its duration.

## What to build

Convert these four sync methods on `RazorpayService` to `async def` using `httpx.AsyncClient`:

- `create_transfer` (line 839) — `POST /v1/transfers`. Razorpay Route standalone transfer (wallet-settlement path, gated by `WALLET_SETTLEMENT_ENABLED`). Mirror `create_payment_transfer` closely — same `X-Transfer-Idempotency` header, same auth, same response shape.
- `fetch_order` (line 323) — `GET /v1/orders/{order_id}`. Called from `handle_order_paid` webhook handler.
- `fetch_payment` (line 289) — `GET /v1/payments/{payment_id}`. Used internally by `fetch_payment_fees` and possibly elsewhere.
- `fetch_payment_fees` (line 312) — internally calls `fetch_payment` (or the same endpoint) and unwraps fee/tax fields. Returns `Optional[Tuple[Decimal, Decimal]]`.

Update all call sites to `await` them.

## What to change

Service-side:
- `backend/services/razorpay_service.py:839` — convert `def create_transfer` to async.
- `backend/services/razorpay_service.py:323` — convert `def fetch_order` to async.
- `backend/services/razorpay_service.py:289` — convert `def fetch_payment` to async.
- `backend/services/razorpay_service.py:312` — convert `def fetch_payment_fees` to async. If it calls `fetch_payment` internally, also `await` that.

Call sites:
- `backend/services/franchisee_settlement_service.py:460` — `razorpay_service.create_transfer(...)` → `await razorpay_service.create_transfer(...)`. Note line 449 already `await`s `create_payment_transfer`; this puts the two branches in parity.
- `backend/routers/webhooks.py:593` — `razorpay_service.fetch_order(order_id)` → `await razorpay_service.fetch_order(order_id)`. Inside `handle_order_paid`.
- `backend/services/qr_payment_service.py:64` — `razorpay_service.fetch_payment_fees(qr_payment.razorpay_payment_id)` → `await razorpay_service.fetch_payment_fees(...)`. Inside `_ensure_actual_fee_captured`. Currently dormant on staging because all QRPayment rows have `fee_source='webhook'`, but the path is exercised whenever a webhook doesn't pre-populate fees.

Confirm via `grep -rn "razorpay_service\.\(create_transfer\|fetch_order\|fetch_payment\b\|fetch_payment_fees\)" backend/` that all callers are updated.

## Acceptance criteria

- [ ] All four methods on `RazorpayService` are `async def` with `httpx.AsyncClient(timeout=10)`.
- [ ] `create_transfer` preserves the `X-Transfer-Idempotency` header behavior — same key + same body returns Razorpay's original response, per the existing docstring.
- [ ] `fetch_payment_fees` still returns `Optional[Tuple[Decimal, Decimal]]` with the same fee/tax unwrapping semantics.
- [ ] All listed call sites are updated to `await` the methods.
- [ ] No remaining sync-call sites for these four methods anywhere in the codebase.
- [ ] Existing tests pass via `docker exec ocpp-backend pytest`.
- [ ] Manual sanity for `fetch_order`: deliver a `payment.captured` or `order.paid` webhook to staging via Razorpay test event replay or a curl against the local webhook endpoint with valid signature; verify the handler completes without blocking the loop (check via py-spy that the loop is responsive during webhook processing).
- [ ] Settlement retry loop (`franchisee_payout_retry_service`, every 600s) completes without freezing the loop. Watch `Heartbeat monitor:` log lines fire continuously during a settlement tick.

## Blocked by

None — can start immediately. Independent of issue 01 (different methods, different call sites).
