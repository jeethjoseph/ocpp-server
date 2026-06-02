Status: done

# Async-ify Razorpay create_order + qr_code CRUD + onboarding fetches (router-initiated)

## Context

See issue 01 for the full background on sync-Razorpay-in-async causing event-loop freezes. The migration template is `razorpay_service.create_payment_transfer` (line 881 of `backend/services/razorpay_service.py`) which uses `httpx.AsyncClient` with `timeout=10`.

This issue covers the **router-initiated** group of sync Razorpay calls — they fire when a user (admin or franchisee) makes an API call. Lower volume than refunds (issue 01) and background workers (issue 02), but they block the requesting user AND every other concurrent request on the same event loop. A franchisee creating a QR code shouldn't freeze chargers' heartbeats.

## What to build

Convert these sync methods on `RazorpayService` to `async def` using `httpx.AsyncClient`:

- `create_order` (line 161) — `POST /v1/orders`. Wallet top-up.
- `create_qr_code` (line 346) — `POST /v1/payments/qr_codes`. QR code creation.
- `close_qr_code` (line 389) — `POST /v1/payments/qr_codes/{id}/close`. QR code closure.
- `fetch_qr_code` (line 411) — `GET /v1/payments/qr_codes/{id}`. (Update if any async callers exist.)
- `fetch_qr_payments` (line 426) — `GET /v1/payments/qr_codes/{id}/payments`.
- `validate_vpa` (line 436) — `POST /v1/payments/validate/vpa`.
- `fetch_linked_account` (line 651) — `GET /v1/accounts/{account_id}`. Onboarding state-fetch.
- `fetch_product_configuration` (line 751) — `GET /v1/products/{product_id}/...`. Onboarding finalize-step.
- `list_stakeholders` (line 787) — `GET /v1/accounts/{account_id}/stakeholders`.
- `fetch_stakeholder` (line 799) — `GET /v1/accounts/{account_id}/stakeholders/{id}`.
- `fetch_transfer` (line 982) — `GET /v1/transfers/{transfer_id}`.
- `reverse_transfer` (line 992) — `POST /v1/transfers/{transfer_id}/reversals`.

Update all call sites to `await` them.

## What to change

Service-side conversions in `backend/services/razorpay_service.py` (lines listed above). Use `create_payment_transfer` (line 881) as the template — same `httpx.AsyncClient(timeout=10)`, same auth tuple, same idempotency-header handling where present.

Call sites (confirm exhaustiveness via `grep -rn "razorpay_service\." backend/ | grep -v 'await\|is_configured\|is_route_enabled\|verify_'` after migration):

- `backend/routers/wallet_payments.py:138` — `razorpay_service.create_order(...)` → `await ...`.
- `backend/routers/franchisee_portal.py:541` — `razorpay_service.create_qr_code(...)` → `await ...`.
- `backend/routers/franchisee_portal.py:658, 705` — `razorpay_service.close_qr_code(...)` → `await ...`.
- `backend/routers/qr_codes.py:47, 63, 146, 284` — mix of `create_qr_code` and `close_qr_code` calls → `await ...`.
- `backend/services/franchisee_onboarding_service.py:416` — `razorpay_service.fetch_linked_account(...)` → `await ...`.
- `backend/services/franchisee_onboarding_service.py:776` — `razorpay_service.fetch_product_configuration(...)` → `await ...`.
- `backend/services/franchisee_onboarding_service.py:826` — `razorpay_service.fetch_stakeholder(...)` → `await ...`.

Any other call sites surfaced by the grep should also be migrated.

## Acceptance criteria

- [ ] All listed methods are `async def` using `httpx.AsyncClient(timeout=10)`.
- [ ] Response shapes preserved (callers don't need changes beyond adding `await`).
- [ ] All known call sites updated to `await`.
- [ ] Final grep confirms no remaining sync `razorpay_service.<method>(` calls (except the genuinely-sync helpers: `is_configured`, `is_route_enabled`, `verify_payment_signature`, `verify_webhook_signature`, and the constructor / module-level singleton `razorpay_service = RazorpayService()`).
- [ ] Existing tests pass via `docker exec ocpp-backend pytest`.
- [ ] Manual sanity: hit `POST /api/admin/qr-codes` and `POST /api/wallet/orders` on staging, confirm both succeed and the OCPP heartbeats keep flowing during the request.

## Blocked by

None — can start immediately. Independent of issues 01, 02.
