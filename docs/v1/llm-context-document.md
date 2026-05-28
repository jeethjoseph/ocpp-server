# OCPP 1.6 CSMS - LLM Context Document

## Overview for AI Assistants

This document provides context for Large Language Models (LLMs) like Claude to understand the current state and architecture of this OCPP 1.6 Charging Station Management System (CSMS) codebase.

---

## Project Summary

**What this system is**: A production-ready Electric Vehicle Charging Station Management System that implements OCPP 1.6 protocol for managing EV charging infrastructure with modern web technologies.

**Current Status**: Actively deployed on AWS EC2 with Docker Compose (backend + frontend + nginx + Redis + PostgreSQL), handling real-world charging stations with WebSocket OCPP communication and QR-based appless charging.

**Version**: 3.1 (March 2026)
**Current Branch**: 57-qr-based-appless-transaction

**Key Capabilities**:
- Real-time OCPP 1.6 communication with charging stations
- Complete transaction lifecycle management with automated billing
- **QR-Based Appless Charging**: Scan UPI QR at charger, pay any amount, charge without app/account
- **Budget Enforcement**: Real-time cost tracking during MeterValues, auto-stop when budget exceeded
- **Automated Refunds**: Unused payment balance refunded via Razorpay after session
- Razorpay payment gateway integration (wallet recharge + QR-based appless charging)
- Zero energy transaction handling (no billing for 0 kWh sessions)
- User transaction history pages with running balance
- Role-based admin dashboard and user interfaces
- Interactive station maps and QR code scanning for users
- Remote charging control (start/stop, availability, reset, firmware OTA)
- Financial integration with wallet system and retry mechanisms
- Docker Compose production deployment with nginx, SSL, monitoring (Sentry + New Relic)

---

## Architecture at a Glance

```
EV Chargers (OCPP 1.6) ←→ FastAPI Backend (Python) ←→ Next.js Frontend (Admin + User)
                ↓                    ↓                    ↓
          WebSocket /ocpp/     PostgreSQL + Redis    Clerk Authentication
                                     ↓                    ↓
                              Capacitor Mobile App (iOS/Android)
                              React + Native Features
```

**Backend**: Python FastAPI 0.115.12 with Tortoise ORM 0.25.1, Redis 6.2.0 for connection state + QR session caching, Clerk JWT (clerk-backend-api 3.1.11) + UPI_GUEST auth
**Web Frontend**: Next.js 15.3.8 with TypeScript 5.x, React 19, TanStack Query 5.81.2 for state, role-based UI (Admin/User)
**Mobile App**: Capacitor 7.4.4 + React 19 + Vite 7.2.4 for native iOS/Android apps with QR scanning, geolocation, payments
**Database**: PostgreSQL with comprehensive schema for charging infrastructure + QR payment tracking
**Protocol**: OCPP 1.6 via WebSocket with full message support
**Authentication**: Clerk (6.29.0 web, 5.56.1 mobile) JWT with role-based access control + UPI_GUEST for appless users
**Payments**: Razorpay SDK 2.0.0 for wallet recharge + UPI QR code generation + refunds
**Deployment**: AWS EC2 with Docker Compose (backend, frontend, nginx, redis). **Both staging and prod postgres are AWS RDS** as of 2026-05-28 — see Database tier section below.
**Monitoring**: Sentry (error tracking) + New Relic (APM) + structured logging
**Testing**: Pytest 8.3.4 with async support

---

## Critical File Locations

### Backend Core (`/backend/`)
- **`main.py`** - FastAPI app with OCPP WebSocket endpoint `/ocpp/{charge_point_id}` and all OCPP message handlers. **QR integration**: StartTransaction links QR payments, MeterValues checks budget, StopTransaction triggers billing/refund. **Transaction resume**: BootNotification resets timeout for already-SUSPENDED transactions (from disconnect handler) or suspends still-active ones. **Socket charger support**: Grace period on Available status instead of immediate failure. **StopTransaction sanitization**: `route_message()` override cleans non-standard reason values
- **`models.py`** - Complete database schema with OCPP enums, User, Charger, Transaction, Wallet, **ChargerQRCode, QRPayment** models
- **`auth_middleware.py`** - Clerk JWT authentication with **RS256 signature verification via `PyJWKClient`** (JWKS URL is env-driven: `CLERK_JWKS_URL` + `CLERK_ISSUER`). Issuer is strictly validated; signature is verified against Clerk's rotating public keys. Role-based access control (ADMIN/USER).
- **`redis_manager.py`** - Real-time connection state management for chargers + **QR session budget caching** (`set_qr_session`, `get_qr_session`, `delete_qr_session`) + **Socket charger grace period** (`set_socket_grace_period`, `get_socket_grace_period`, `delete_socket_grace_period`)
- **`core/connection_manager.py`** - Centralized charger connection management with tombstone mechanism, heartbeat monitoring (120s timeout), ghost session detection, OCPP command dispatch (RemoteStart/Stop, ChangeAvailability, UpdateFirmware, Reset), **disconnect callback hook** (`register_on_disconnect`) for transaction suspension
- **`tortoise_config.py`** - Database configuration with SSL for production

### API Routing (`/backend/routers/`)
- **`stations.py`** - Station CRUD with geographic data (`/api/admin/stations/*`)
- **`chargers.py`** - OCPP charger management with remote commands (`/api/admin/chargers/*`)
- **`transactions.py`** - Transaction tracking with meter values (`/api/admin/transactions/*`)
- **`users.py`** - User management with wallet operations (`/users/*`)
- **`firmware.py`** - **Firmware OTA update management** (`/api/admin/firmware/*` + `/api/firmware/*`)
  - Admin: Upload, list, delete firmware files
  - Admin: Trigger OCPP firmware updates (single/bulk)
  - Admin: Monitor update progress with real-time dashboard
  - Public: `/api/firmware/latest` for non-OCPP charge points
- **`public_stations.py`** - Public unauthenticated station/charger discovery (`/api/public/stations/*`) for user-facing pages. **`ConnectorInfo` (2026-05-21)** carries per-plug-type `ready_count`/`in_use_count`/`out_of_service_count` (3-bucket mapping from `ChargerStatusEnum` via `_status_bucket`) plus per-plug-type `min_tariff_all_in`/`max_tariff_all_in`. Legacy `available_count`/`total_count` are still emitted (=`ready_count`/total) for `/stations` and the map popup.
- **`public_qr_transactions.py`** - Public QR transaction history lookup by UPI VPA (`/api/public/qr-transactions`) — no auth, paginated, minimal data exposure. **Refund lifecycle (2026-05-21, ADR 0005)**: response carries `razorpay_refund_id`, `razorpay_refund_speed_processed`, `refund_processed_at`, `refund_failure_reason` so the customer-facing card can render Initiated / Sent to bank / Failed without ever claiming "credited to source account" for normal-speed refunds (which Razorpay genuinely can't confirm).
- **`public_qr_active_sessions.py`** - Public no-auth endpoint (`GET /api/public/qr-active-sessions?vpa=X`, 2026-05-21) returning in-progress QR sessions for a VPA, classified into 4 customer-facing sub-states (`waiting` / `charging` / `paused` / `stopping`) by the **canonical classifier in `services/qr_session_state.py`** which is the single source of truth for "is this QR session active?" — `customer_sub_state(qr_payment, transaction, stale_threshold_seconds=...)`. **Live KPIs come entirely from the `qr_session:{txn_id}` Redis row** (2026-05-22, Option 1 of review item #4): `check_budget_and_auto_stop` stamps `latest_reading_kwh` / `latest_power_kw` / `latest_meter_at` on every MeterValues frame, and the endpoint reads these without an additional DB query. Pre-first-frame / cache-rebuild falls back to a one-row MeterValue query. Computes `energy_kwh`, `spent_so_far`, `refund_if_stopped_now` (no longer a duplicate `budget_remaining` — issue 06). `waiting` entries also carry `stale_threshold_seconds` so the frontend can render specific auto-refund-window copy. Same 20 req/60s/IP rate limit as the history endpoint. **Hardening (2026-05-21):** per-session `try/except` so one bad row doesn't 500 the request; emits `Custom/ActiveSession/Request|CacheMiss|SessionComputeError|SubState/<state>` counters. VPA pattern lives in shared `core/validators.py` (imported by both QR routers). **Read-only by design — see ADR 0006**: no remote-stop action is exposed behind the VPA check because VPAs aren't credentials.
- **`qr_codes.py`** - Admin QR code CRUD for appless charging (`/api/admin/qr-codes/*`)
  - Create/list/close/regenerate QR codes linked to chargers
  - Payment history and revenue stats per QR code
  - All QRs are platform-owned: payments land in VoltLync's nodal balance, never scoped to a franchisee's linked account. The franchisee's share is disbursed via a Route transfer *after* the session settles (see `franchisee_settlement_service`). Legacy rows with `ChargerQRCode.owner_razorpay_account_id IS NOT NULL` must be regenerated via the close-and-recreate endpoint before new payments flow correctly.
  - Multiple `ChargerQRCode` rows per charger are permitted (one active + many closed). Migration 41 (2026-05-25) dropped the stale Postgres-default `charger_qr_code_charger_id_key` UNIQUE constraint that migration 12 had failed to remove (wrong name in `DROP INDEX IF EXISTS`). Without 41, close-then-recreate raises 500 with `asyncpg.UniqueViolationError`. The create endpoint enforces the at-most-one-*active* rule at the application layer (`backend/routers/qr_codes.py`).
- **`franchisee_portal.py`** - Franchisee-facing portal API (`/api/franchisee/*`)
  - Dashboard, stations, chargers, transactions, settlements, profile, QR codes
  - `/qr-codes` endpoints support full CRUD on the franchisee's own chargers' QRs (list with `can_create_direct` / `payee_display_name`, create, regenerate, close). Regenerate is the retroactive compliance path: once Razorpay KYC completes, the franchisee clicks it to upgrade each platform-owned QR into a franchisee-owned one. All mutations audit-log with `actor_type=franchisee`.
- **`webhooks.py`** - Clerk webhook processing for user lifecycle (`/webhooks/clerk`) + Razorpay webhook handler (`/webhooks/razorpay`). **`handle_refund_event` (2026-05-21)** now handles three event types — `refund.processed` stamps `refund_processed_at` AND captures `speed_processed`; `refund.failed` records `refund_failure_reason`; **`refund.speed_changed`** updates `razorpay_refund_speed_processed` when Razorpay silently downgrades instant→normal (or upgrades), keeping the customer-facing ETA honest per ADR 0005.
  - Routes `qr_code.credited` events to `QRPaymentService.handle_qr_payment()`
- **`wallet_payments.py`** - Razorpay payment integration for wallet recharge (`/api/wallet/*`)
- **`ocpp_ws.py`** - OCPP WebSocket endpoint routing
- **`logs.py`** - Admin OCPP log viewing

### Business Services (`/backend/services/`)
- **`qr_payment_service.py`** - **NEW**: Complete QR-based appless charging lifecycle (~600 lines)
  - `handle_qr_payment()` - Main webhook entry: idempotency → staleness → user resolution → charging trigger
  - `find_or_create_user_from_payment()` - Priority: phone → VPA → UPI_GUEST → system guest
  - `link_transaction_to_qr_payment()` - Called from StartTransaction, caches budget in Redis
  - `check_budget_and_auto_stop()` - Called from MeterValues, schedules RemoteStop if budget exceeded
  - `process_qr_session_billing()` - Called from StopTransaction, calculates cost with GST, issues refund. Formula: `energy_charge = energy_kwh * rate`, `gst = energy_charge * gst_percent / 100`, `refund = amount_paid - energy_charge - gst - synthetic_platform_fee` (synthetic, NOT actual — see below).
  - `_ensure_actual_fee_captured(qr_payment)` - Side-effect writer: ensures the actual Razorpay fee lives on the QRPayment row. Priority: stored webhook value > Razorpay API fetch > 2% estimate fallback. Returns nothing. Used only for ops/reconciliation. Stays in `qr_payment_service.py` because it talks to the Razorpay SDK.
  - **Shared synthetic-fee helpers live in `services/tariff_utils.py`** (post-2026-05-18 module reorg): public `synthetic_platform_fee(amount_paid)` returns `amount_paid × RAZORPAY_PLATFORM_FEE_PERCENT/100`; public `synthetic_fee_split(amount_paid)` returns `(commission, gst)` with commission = `× 2/118` and GST as the residual. Both consumed by `qr_payment_service.process_qr_session_billing` AND `invoice_service.generate_invoice`.
  - Fee fields on QRPayment: `platform_fee` (actual total fee), `razorpay_commission` (fee - tax), `razorpay_gst` (tax), `fee_source` ('webhook'|'api'|'estimated'). These hold the **actual** Razorpay deduction — NOT what appears on the customer's invoice.
  - Config: `RAZORPAY_PLATFORM_FEE_PERCENT=2.0` lives in `backend/core/config.py` (project-level config home). Now the **authoritative** synthetic rate, not a fallback. **Validated at startup across four bands** via `validate_platform_fee_percent`: `≤0` → `RuntimeError` (would zero out customer-facing math); `0–5%` → info log, normal startup; `>5–10%` → `ERROR` log warning, startup proceeds (legitimately high but ops should review); `>10%` → `RuntimeError` (almost certainly off-by-decimal-point). `QR_PAYMENT_PENDING_TIMEOUT=300` stays in `qr_payment_service` (QR-only).
  - **Refund policy (2026-05-13)**: any positive balance is refunded via Razorpay regardless of magnitude — the historical `MINIMUM_REFUND_AMOUNT` threshold has been removed. Negative balance (over-delivered energy) is absorbed as operator loss. Invariant `transaction_amount = total_amount + refund_amount` holds on every new QR invoice.
  - **Zero-energy refund policy (2026-05-18, ADR 0002)**: when `energy_consumed_kwh ≤ 0`, `handle_charging_failure` → `_full_refund` refunds the entire `amount_paid`, NOT `amount_paid - platform_fee`. The actual Razorpay fee is still captured to the QRPayment row (`platform_fee`/`razorpay_commission`/`razorpay_gst`) for ops/reconciliation but is ignored by the refund formula. VoltLync absorbs the gateway fee and refund-processing fee as P&L. No `GSTInvoice` is issued (invoice service short-circuits at `energy <= 0`). See `docs/adr/0002-zero-energy-full-refund.md`.
  - **Razorpay instant refunds for full-refund flows (2026-05-20, ADR 0002 amendment)**: all six `_full_refund` call sites (zero-energy stop, stale payment, concurrent rejection, charger not connected, RemoteStart fail, plug-in timeout) request `speed=optimum` so customers see refunds in minutes instead of 5–7 working days. VoltLync absorbs Razorpay's per-refund instant fee (~₹5–6 + GST) on top of the original capture fee. `process_qr_session_billing` partial unused-credit refunds stay on normal speed. `RazorpayService.refund_payment` logs `speed_requested` and `speed_processed` on every call. The outcome is also **persisted** on `QRPayment.razorpay_refund_speed_processed` (VARCHAR(20), nullable; migration 40) and surfaced as an `Instant`/`Normal (5-7 days)` badge on the admin QR detail page next to the refund amount. **New Relic counters** `Custom/QR/RefundInstantSucceeded` and `Custom/QR/RefundInstantFallback` (emitted via `OCPPMetrics.record_refund_speed`, only when `speed=optimum` was actually requested) let ops alert on a sudden fallback spike (rail outage, account-level rate limit, payment-method shift). Kill-switch: `RAZORPAY_INSTANT_REFUND_ENABLED` env var (default `true`) — flip to `false` and redeploy to revert to normal speed in an incident; the counters intentionally do not fire when the flag is off, because a normal-speed refund is not a "fallback."
  - **`gst_invoice.gateway_charges` and `gateway_gst`** (post-2026-05-18, ADR 0001) snapshot the **synthetic** 2% split of `qr_payment.amount_paid` at issue time, NOT the actual webhook values on the QRPayment row. NULL for wallet rows. Customers see a deterministic 2% gateway line regardless of what Razorpay actually charged. The actual-vs-synthetic variance is queryable via `SUM(qr_payment.platform_fee - 0.02 × amount_paid)`.
  - **Tariff identity drift checker:** `services/tariff_drift_check.py` runs on startup. Samples a few `Tariff` rows and warns if the back-calc identity (`back_derive_rate_per_kwh(all_in, gst, current_fee) ≈ stored rate_per_kwh`) is violated — catches the case where `RAZORPAY_PLATFORM_FEE_PERCENT` was changed after migration 36 ran. Emits `Custom/Tariff/IdentityDrift` (counter, once per startup). Operators clear drift by re-saving the affected tariff via the admin form.
- **`wallet_service.py`** - Billing calculations and automated payment processing
  - Zero energy transaction handling (no billing for 0 kWh)
  - Wallet top-up processing with idempotency (`process_wallet_topup()`)
  - Atomic transaction processing with SELECT FOR UPDATE
  - Tariff-based billing calculation with GST: `energy_charge = energy_kwh * rate_per_kwh`, `gst = energy_charge * gst_percent / 100`, `total = energy_charge + gst` (default 18% GST, configurable per tariff via `gst_percent` field)
  - **Admin tariff edits use the all-inclusive input (post-2026-05-18, ADR 0003).** `POST/PUT /api/admin/chargers` accept ONLY `tariff_per_kwh_all_in: float, 1.0–100.0` for tariff. The router back-derives `rate_per_kwh = all_in × (1 - 2/100) / (1 + gst_percent/100)` via `tariff_utils.back_derive_rate_per_kwh` and persists both columns. The pre-ADR-0003 fields `tariff_per_kwh` and `tariff_per_kwh_incl_tax` are rejected with 422 (`extra='forbid'` on the Pydantic schema). `GET /api/admin/chargers` and `GET /api/admin/chargers/{id}` echo back `tariff_per_kwh_all_in` alongside `tariff_per_kwh` (internal, back-derived) and `tariff_gst_percent`.
  - **Frontend constants mirror backend defaults.** `frontend/lib/constants.ts` exports `PLATFORM_FEE_PERCENT = 2` and `DEFAULT_GST_PERCENT = 18` so the admin tariff form's `TariffBreakdownPreview` (extracted to `frontend/components/TariffBreakdownPreview.tsx` for testability) shows the right labels without hardcoding. Keep `constants.ts` in sync with `backend/core/config.py` and the `Tariff.gst_percent` default — there's no automatic propagation.
  - **Frontend test harness** lives at `frontend/__tests__/` (Vitest + React Testing Library + jsdom). Run `npm test` (watch) or `npm run test:run` (one-shot). Today covers `formatTariffRangeAllIn`, `breakdownAllInTariff`, and `TariffBreakdownPreview` — the customer-facing pricing math + the admin preview component that mirrors backend `back_derive_rate_per_kwh`. See `frontend/__tests__/README.md` for conventions and the "no CI today" note.
  - **`backend/scripts/seed_data.py`** picks `tariff_per_kwh_all_in` first and back-derives `rate_per_kwh` via `back_derive_rate_per_kwh`, so seeded dev fixtures satisfy the runtime identity check from `services/tariff_drift_check.py`. Reseeding dev data should never trigger the drift warning.
  - **All user-facing tariff displays use the all-inclusive figure (post-2026-05-18, ADR 0003).** The operator-typed `Tariff.tariff_per_kwh_all_in` is the source of truth for display. Public station endpoints expose per-charger `tariff_per_kwh_all_in`/`tariff_gst_percent` on `StationChargerInfo` plus station-level `min/max_price_per_kwh_all_in`. The user-facing charger detail endpoint (`GET /api/users/chargers/{id}`) returns `tariff_per_kwh_all_in`. The station-range helper lives in `backend/services/tariff_utils.py` (`compute_station_tariff_range`, `back_derive_rate_per_kwh`). Frontend renders the all-in figure with an `(all-inclusive)` label via `formatTariffRangeAllIn` in `frontend/lib/utils.ts`. The admin chargers create/edit form takes a single `tariff_per_kwh_all_in` input (₹1.0–100.0 validated client- and server-side) and shows a live `TariffBreakdownPreview` panel below the input as the operator types — three rows showing the back-derived `rate_per_kwh`, the gateway-fee per kWh, and the GST per kWh — driven by `breakdownAllInTariff` in `frontend/lib/utils.ts`. The legacy `tariff_per_kwh` / `tariff_per_kwh_incl_tax` form fields and their derived-rate footnotes were removed.
  - **Post-migration re-entry is manual.** Migration 36 shrinks `rate_per_kwh` by 2% so customer-facing prices stay constant; franchisees absorb the 2% on legacy tariffs until they re-save via the new API. At the time of ADR 0003 there are only two live chargers — the ops team handles re-entry manually and the originally-planned legacy-tariff banner endpoint was dropped as redundant. See ADR 0003 for when to add it back.
- **`charger_type_service.py`** - **NEW**: Socket charger detection helpers
  - `is_socket_charger()` - DB lookup for socket connector type
  - `is_socket_charger_cached()` - In-memory cache with DB fallback
  - `should_use_grace_period()` - Returns True only for Available status (not Faulted/Unavailable)
- **`disconnect_handler.py`** - **Disconnect-aware transaction suspension**
  - `suspend_transactions_on_disconnect()` - Suspends active transactions when charger disconnects, starts 180s timeout, initializes flap counter
  - `_disconnect_suspend_timeout()` - Auto-stops SUSPENDED transactions after timeout with CAS guard, delegates to `transaction_finalizer.finalize_stopped_transaction`
  - `sweep_stale_suspended_transactions()` - Startup safety net for orphaned SUSPENDED transactions after server restart, delegates to `transaction_finalizer`
  - `_disconnect_reset_count` - In-memory dict tracking *consecutive disconnects without energy progress* per transaction. Pathological-flap detector — counter is checked in main.py BootNotification handler and zeroed in `zero_energy_watchdog.check_zero_energy` when MeterValues show real charging progress
  - Config: `DISCONNECT_SUSPEND_TIMEOUT_SECONDS=180`, `MAX_DISCONNECT_RESETS_WITHOUT_PROGRESS=3`
- **`transaction_finalizer.py`** - **NEW**: Single source of truth for stopping transactions on timeout
  - `finalize_stopped_transaction(transaction, stop_reason)` - Idempotent: calculates final energy from latest MeterValue, marks STOPPED, audit-logs, processes wallet billing, processes QR billing/refund, cleans up zero-energy redis state and flap counter
  - `is_resume_too_stale(transaction)` - **Defense-in-depth resume staleness guard.** Returns `(is_stale, gap_seconds)` based on the most recent of `suspended_at`, latest MeterValue.created_at, or `start_time`. Threshold `MAX_RESUME_GAP_SECONDS=900` (configurable). Called at all three resume points in `main.py` so a txn whose primary suspend/timeout chain failed cannot be silently resumed and overcharged. Stop reason on stale finalize: `STALE_RECONNECT`. Audit action: `transaction.resume_blocked` (with `trigger`, `gap_seconds`, `previous_status` in changes payload).
  - Replaces duplicated stop-and-bill logic that previously lived in both `main.py:_suspend_timeout` and `disconnect_handler._stop_and_bill_transaction`
  - Used by: `main.py` BootNotification suspend timeout, `disconnect_handler` disconnect timeout, `disconnect_handler` startup sweep, all three resume points (MeterValues auto-resume, BootNotification per-txn handler, GetLastMeterValue DataTransfer)
- **`zero_energy_watchdog.py`** - Auto-stop for stalled charging sessions
  - `check_zero_energy()` - Called from MeterValues handler. Tracks energy progress in Redis, schedules `RemoteStopTransaction` if energy hasn't advanced for `ZERO_ENERGY_TIMEOUT_SECONDS` (7200s / 2h since 2026-05-21) after `ZERO_ENERGY_GRACE_PERIOD_SECONDS` (60s) grace. The 2h window was chosen so EVs that taper-complete (SOC limit / BMS pause) aren't killed mid-taper — operators can manually stop or the watchdog will eventually finalize.
  - **Invariant**: Redis state TTL (`set_zero_energy_state` in `redis_manager.py`, currently 14400s) MUST remain strictly greater than `ZERO_ENERGY_TIMEOUT_SECONDS`, otherwise a charger that goes silent mid-stall lets the state expire and resets the stall clock on reconnect
  - **W5 hook**: when energy advances, pops `disconnect_handler._disconnect_reset_count` for the transaction, allowing long sessions with intermittent disconnects to never trip the flap detector
  - `clear_zero_energy_tracking()` - Cleanup hook called from `transaction_finalizer.finalize_stopped_transaction`
  - Config: `ZERO_ENERGY_TIMEOUT_SECONDS=7200`, `ZERO_ENERGY_GRACE_PERIOD_SECONDS=60`
- **`billing_retry_service.py`** - Background service (30-min interval) for failed transaction recovery, QR refund retries, orphaned QR payment cleanup, stale suspended transaction cleanup
- **`firmware_update_service.py`** - Background service for OCPP firmware updates (v2 state machine, migration 35)
  - **State machine**: only 4 states — PENDING / INSTALLED / FAILED / CANCELLED. Intermediate states (DOWNLOADING/DOWNLOADED/INSTALLING) and split failures (DOWNLOAD_FAILED/INSTALLATION_FAILED) were collapsed in migration 35.
  - **Source of truth for completion**: BootNotification with charger-reported `firmware_version` matching the pending target. `FirmwareStatusNotification` is logging-only — Quectel modems suspend WSS during HTTPS firmware download, so FSN messages are not reliable.
  - **Retry scheduler**: Phase A sends `UpdateFirmware` for due rows (never attempted, or `next_retry_at <= now`). Phase B declares attempts failed when `last_attempt_at` is older than `FIRMWARE_ATTEMPT_TIMEOUT_SECONDS` with no `next_retry_at` (no boot received). Exponential backoff: 5m → 30m → 2h → 4h. Defaults: 5 attempts / 6h wall-clock (`FIRMWARE_MAX_ATTEMPTS`, `FIRMWARE_MAX_ELAPSED_SECONDS`).
  - **handle_boot_notification(charger, reported_version)**: called from main.py's BootNotification handler. Marks INSTALLED on match. Ignores boots inside `FIRMWARE_BOOT_DEBOUNCE_SECONDS` window (charger may still be mid-download). Applies backoff on mismatch outside debounce.
  - **WS-drop expectation**: after a successful `UpdateFirmware` send, marks `connected_charge_points[cp_id]["expected_ws_drop_until"] = now + 30min` so disconnect handlers don't alarm.
- **`razorpay_service.py`** - Razorpay payment gateway integration
  - Order creation and payment verification
  - Webhook signature verification (HMAC SHA256)
  - **QR code creation**: `create_qr_code(payee_name, description, account_id=None)`, `close_qr_code(id, account_id=None)`, `fetch_qr_code(id, account_id=None)`. `account_id` is still accepted for backward-compatible close/fetch on legacy franchisee-scoped QRs but NEW QRs are always created with `account_id=None` (platform-owned); the franchisee's share is transferred post-settlement via Route.
  - **Helpers**: `build_qr_payee_name(business_name, charger_name)` composes the `name` metadata (50-char cap; falls back to "VoltLync" when no franchisee). `build_qr_description(...)` composes the rendered descriptor line.
  - **Refunds**: `refund_payment(payment_id, amount, notes, idempotency_key)` — `idempotency_key` is sent as `X-Refund-Idempotency` so retries dedupe server-side. Callers use `f"qr_payment_{id}"` as the stable key.
  - **Known issue — webhook fees vs settled fees**: `qr_code.credited` webhook delivers Razorpay's *plan-rate* fee, which gets zeroed for UPI P2M ≤ ₹2000 by settlement time without notification. `_resolve_platform_fee` trusts the webhook value. Causes small under-refunds and under-payouts. Documented at `docs/known-issues.md#1`.
  - **Route transfers**: two endpoints, picked in `franchisee_settlement_service.initiate_transfer` based on whether the ledger entry has a source `razorpay_payment_id`:
    - **Payment-based** (QR sessions): `create_payment_transfer(payment_id, account_id, amount_paise, notes, franchisee_id)` → `POST /v1/payments/{id}/transfers`. No on-demand activation required. Wraps `requests.post` directly (not the SDK) and writes a `RazorpayApiLog` audit row via `_audit_call`. Razorpay's only constraint is `sum(transfers) ≤ captured_amount`; refunds reduce the effective transferable amount. App-level idempotency comes from `_validate_ledger_for_transfer`'s `razorpay_payment_id` collision check (no `X-Transfer-Idempotency` header is sent).
    - **Direct** (wallet sessions): `create_transfer(account_id, amount_paise, notes, idempotency_key)` → `POST /v1/transfers`. `idempotency_key` is sent as `X-Transfer-Idempotency`. **This endpoint is gated by an on-demand Razorpay merchant feature** ("Direct Transfers") and returns `400 "This feature is not enabled for this merchant."` until ops opens a support ticket on the parent merchant.
  - **`WALLET_SETTLEMENT_ENABLED` env flag** (default `false`): until the Direct Transfers feature is activated, wallet-session ledger entries are parked in `ON_HOLD` with `failure_reason="wallet_settlement_not_activated"` and **skipped by `retry_failed_transfers`** (the retry sweep filters out entries with `razorpay_payment_id IS NULL` while the flag is off). When ops activates the feature on Razorpay and flips the flag to `true`, the same retry sweep picks the held entries up automatically. QR/UPI settlements (which use the payment-based endpoint) are unaffected by this flag. Wallet top-ups themselves are not gated — admins/users can still top-up and use wallet credit at VoltLync-owned chargers; only franchisee-bound transfers are deferred.
  - **Linked accounts**: `create_linked_account(payload)` — caller builds the payload including `reference_id=f"franchisee_{id}"`, `business_type`, `contact_name`, and `profile.category/subcategory` + `profile.addresses.registered` (street1/street2/city/state/postal_code/country). The addresses block is mandatory per Razorpay; `franchisee_onboarding_service` fails early with a readable `RuntimeError` when `address`, `city`, `state`, or `pincode` is missing on the Franchisee record. Razorpay SDK errors are caught in `routers/franchisees.onboard_to_razorpay` and returned as HTTP 400 with the Razorpay message so the admin UI shows the actual cause, not "Internal Server Error". Razorpay emails the franchisee a KYC invite directly; no hosted onboarding URL is relied on.
  - Test/Live mode support
- **`monitoring_service.py`** - Sentry + New Relic integration
  - `@trace_transaction` decorator for OCPP message tracing
  - `MetricsCollector`, `OCPPMetrics`, `SentryHelper` classes
  - **W6 metrics for failure-mode alerting**: `record_disconnect_suspended`, `record_disconnect_stopped`, `record_zero_energy_stopped`, `record_billing_failed`, `record_stale_suspended_swept` — all paired with `Custom/OCPP/...` counters and structured events. Linked from runbooks in `docs/runbooks/`.
  - **WebSocket lifecycle events (2026-05-28)**: `record_websocket_disconnect` emits `OCPPWebSocketDisconnect` from `core/connection_manager.force_disconnect` (the single chokepoint — every disconnect path flows through it). Attributes: `charger_id`, `disconnect_category` (one of `client_close`, `server_error`, `stale_replaced`, `heartbeat_timeout`, `ops_initiated`), `duration_seconds`, `ws_close_code`, `ws_close_reason`, `had_active_transaction`, `transaction_id`, `heartbeat_seconds_since_last`, `messages_received`, `reason_text`. `record_websocket_rejected` emits `OCPPWebSocketRejected` from the tombstone (`code=1013`) and validation_failed (`code=1008`) reject paths in `routers/ocpp_ws.py` — connect-time rejections that never reach `cp.start()`. Per-category counters (`Custom/OCPP/Disconnects/{category}`, `Custom/OCPP/Rejects/{reason}`) have 13-month retention; the rich events have 8–30 day retention. Shipped as an **investigative campaign** to baseline disconnect frequency and decide whether `OCPP_TIMEOUT=120s` needs tuning — see `.scratch/ws-disconnect-tracking/`.
- **`storage_service.py`** - **Firmware file storage**
  - **Primary storage**: S3 with presigned GET URLs. Bucket: `AWS_S3_FIRMWARE_BUCKET`. Region: `AWS_REGION` (default `ap-south-1`). Same boto3 client pattern as `s3_service.py` (invoice PDFs).
  - **Presigned URL TTL**: `max(FIRMWARE_MAX_ELAPSED_SECONDS, 24h) + 1h` — sized to outlive the 6h retry window so a URL handed out at attempt 1 is still valid at attempt 5.
  - **Key shape**: `firmware/{sanitized_version}/{sanitized_filename}`. Built via `build_firmware_s3_key()`.
  - **Helpers**: `upload_firmware_to_s3(s3_key, bytes)`, `generate_firmware_presigned_url(s3_key)`, `get_firmware_download_url_for_file(firmware_file)` (prefers S3, falls back to legacy local-mount URL when `s3_key` is null).
  - **Legacy fallback**: rows uploaded before migration 35 have `FirmwareFile.s3_key=NULL` and are still served via the local `/firmware/{filename}` StaticFiles mount. A one-time migration script (follow-up) backfills `s3_key` and uploads existing files; once all rows have `s3_key`, the StaticFiles mount can be removed.
  - **Storage-backend stopgap (2026-05-20)**: `POST /api/admin/firmware/upload` branches on `AWS_S3_FIRMWARE_BUCKET`. Bucket name set → S3 upload + `s3_key` populated. Empty/unset → file written to `/app/firmware_files/{filename}` on the container, `s3_key=NULL`, `file_path` populated. The legacy fallback path in `get_firmware_download_url_for_file` automatically serves the short ~62-byte URL (`{FIRMWARE_PUBLIC_BASE_URL}/firmware/{filename}`) for rows where `s3_key IS NULL`. Audit log records `storage_backend: "s3" | "local"`. Stopgap to unblock chargers whose firmware URL parser can't handle the ~1.7KB S3 presigned URL (caused by `X-Amz-Security-Token` from EC2 instance-role temp creds). Flip back by setting the env var. See `.scratch/firmware-update-hardening/issues/01-…` for the rollout. **Do not enable empty-bucket mode on prod** without a token-based proxy — the legacy URL has no signature/TTL.
  - **Legacy volume**: `backend_firmware_{env}` named Docker volume retained for fallback. `docker-entrypoint.sh` still chowns `/app/firmware_files` to `app:app` for the legacy path.
- **`data_retention_service.py`** - **Background data cleanup service**
  - Automated cleanup of old signal quality data (90 days retention)
  - OCPP log cleanup (90 days retention)
  - Runs every 24 hours
  - Configurable retention period and cleanup interval
- **`clerk_invitation_service.py`** - **Clerk sign-up invitation helper**
  - Used by the franchisee onboarding flow: when admin creates a
    franchisee, we fire a Clerk invitation seeded with
    `public_metadata.role = "FRANCHISEE"` so the new user lands in the
    portal on first login with no manual role editing.
  - `send_invitation(email, role, redirect_path)` creates + emails
    the invite via `clerk_backend_api`. Idempotent: "already
    invited/registered" errors are swallowed.
  - `revoke_pending_invitation(email)` used by the resend endpoint.
  - `push_role_to_clerk(clerk_user_id, role)` called from the Clerk
    `user.created` webhook to self-heal role drift when a user signs
    up without using the invitation link.
  - Needs `CLERK_SECRET_KEY` and `FRONTEND_URL` env vars.
- **`franchisee_onboarding_service.py`** - **Razorpay Route KYC flow**
  - `create_linked_account(franchisee_id)` creates a Razorpay linked
    account with full payload: `reference_id=f"f_{id}_{epoch}"`
    (≤20 chars per Razorpay's hard cap), `legal_business_name`,
    `customer_facing_business_name`, `business_type` (mapped via
    `_BUSINESS_TYPE_MAP` from our `FranchiseeBusinessTypeEnum`),
    `contact_name`, `profile.category/subcategory`
    (`services / automotive_service_shops`). Fails fast with a
    `RuntimeError` if `business_type` is not yet set on the franchisee
    — admin must fill it via the Business Details edit dialog before
    calling onboarding. Persists any optional `hosted_onboarding_url`
    from the response (best-effort; Razorpay emails the franchisee
    directly regardless).
    **Subcategory history (2026-04-30):** earlier versions sent
    `utilities/electric_vehicle_charging` then `services/service_stations`.
    Both were rejected by KYC review and parked accounts in
    `needs_clarification + requirements: []` (broken signal —
    Razorpay's API enum is lowercase-strict and `service_stations` is
    not in support's approved subset). Diagnostic PATCH on
    `acc_SjK7ZBzAfiA4QF` confirmed `automotive_service_shops`
    activates immediately — see `docs/razorpay-onboarding-acc_SjK7ZBzAfiA4QF.md`
    "Resolution" section.
  - `handle_account_webhook(event_type, data)` advances the franchisee
    status machine on Razorpay account events. Subscribed events
    handled: `account.activated`, `account.instantly_activated`,
    `account.activated_kyc_pending`, `account.under_review`,
    `account.needs_clarification`, `account.rejected`,
    `account.updated` (generic catch-all). **Not subscribed /
    not emitted by Razorpay**: `account.suspended`,
    `account.funds_onhold`, `account.funds_unhold` — the
    corresponding `Franchisee.transfers_enabled` /
    `funds_on_hold` / `SUSPENDED` status fields exist but are
    only ever toggled by admin action or rejected-account webhook,
    not by a dedicated Razorpay webhook.
  - `refresh_kyc_status(franchisee_id)` polls Razorpay for current
    account status when webhooks aren't trusted.
  - **Post-create KYC submission chain** (API-driven, bypasses the
    Razorpay dashboard's broken KYC Form): `ensure_product_config`
    POSTs `/v2/accounts/{id}/products` and persists the returned
    `product_id` on `Franchisee.razorpay_product_id`; `submit_bank_details`
    PATCHes the product config with `settlements`
    (`account_number` / `ifsc_code` / `beneficiary_name` only —
    Razorpay rejects `account_type` with "account_type is/are not
    required and should not be sent", verified 2026-04-29 via the
    audit log) plus `tnc_accepted: true` (re-sent on every PATCH per
    Razorpay's update-product-config doc). The
    `Franchisee.bank_account_type` column is kept locally for
    invoicing / reconciliation but is NOT sent to Razorpay.
  - **Pre-transfer validator** (`_validate_ledger_for_transfer`) runs
    six foolproof checks before each `create_transfer`: positive
    payout, payout ≤ gross − refund, components sum to gross within
    a 2-paisa tolerance, settlement_status not in a terminal state,
    franchisee has a matching razorpay_account_id, and
    razorpay_payment_id (when present) hasn't already been used on a
    sibling ledger entry's transfer. Math/state failures mark the
    entry FAILED but do NOT increment retry_count — they require admin
    investigation, not blind retry.
  - **Background payout retry service**
    (`backend/services/franchisee_payout_retry_service.py`, started
    from `main.py` startup) wakes every
    `FRANCHISEE_PAYOUT_RETRY_INTERVAL_SECONDS` (default 600) and calls
    `retry_failed_transfers()` to drain ON_HOLD/FAILED entries. No-op
    when `RAZORPAY_ROUTE_ENABLED != "true"`. Closes the loop on
    cooling-period and funds_unhold gates that have since cleared.
  - **Razorpay-side audit notes**: `create_transfer` payload `notes`
    carries `transaction_id`, `ledger_entry_id`, `franchisee_id`,
    `voltlync_payment_id` (the source `razorpay_payment_id` or
    "wallet"), and `idempotency_key`, so an operator looking at a
    transfer in the Razorpay dashboard can trace back to the
    originating payment without joining our DB.
    **Name-chain requirement (advisory only, not enforced):** Razorpay
    requires the bank-passbook account-holder name ==
    `settlements.beneficiary_name` (PATCH product config) ==
    `legal_business_name` (POST /v2/accounts). Today
    `beneficiary_name` is sourced from `franchisee.bank_account_name`
    while `legal_business_name` comes from `franchisee.business_name`;
    nothing enforces equality. The franchisee detail page surfaces an
    advisory note in the Bank Account section. Hard enforcement is
    pending confirmation from Razorpay support that the rule applies
    uniformly across all `business_type` values.
    `add_stakeholder` POSTs to
    `/stakeholders` with `kyc.pan` + optional `addresses.residential`
    and mirrors the result into `FranchiseeStakeholder`. The top-level
    `submit_kyc(franchisee_id)` orchestrates ensure_product_config +
    submit_bank_details + fetch, returning `{activation_status,
    requirements[], stakeholder_count}`. `update_stakeholder` PATCHes
    an existing Razorpay stakeholder + persists locally — used to
    backfill PAN / residential address when admins forgot at create
    time. `reconcile_razorpay` back-fills product_id + stakeholder rows
    for accounts pushed to Razorpay outside this flow (e.g. via one-off
    scripts). Razorpay's dashboard KYC Form omits stakeholder entry for
    `business_type=not_yet_registered` (proprietorship), so the API path
    is the only way to get past `activation_status: created` for those
    accounts.
  - **Relationship defaults by business_type** (`_relationship_defaults`):
    INDIVIDUAL / PROPRIETORSHIP → `(director=False, executive=True)` —
    proprietors aren't directors. PARTNERSHIP / PRIVATE_LIMITED / LLP →
    `(True, True)`. The wrong defaults (uniform `True/True`) caused the
    `acc_Sg73UwyOU3jziR` stuck-account audit, even though Razorpay
    accepted them on the wire — they're semantically wrong metadata for
    individuals and may delay automated review.
  - **`addresses.registered` only** on `create_linked_account` —
    Razorpay rejects `addresses.operational` for `business_type:
    individual` with `"operational is/are not required and should not be
    sent"` (verified 2026-04-29 via `razorpay_api_log`; the Tier 1+2
    hypothesis that `operational` was a documented optional field turned
    out to be wrong). After create, we log a WARNING if Razorpay echoes
    back a `business_type` different from what we sent (Razorpay
    silently downgraded `individual` → `not_yet_registered` for
    `acc_Sg73UwyOU3jziR`).
  - **KYC verification status** — Razorpay ships per-dimension
    verification fields (`bank_details_verification_status`,
    `poi_verification_status`, `poa_verification_status`, etc.) on
    `account.under_review` / `account.needs_clarification` payloads.
    These are persisted on `Franchisee.kyc_verifications` (JSONB) and
    surfaced on the admin detail page so admins can see which dimension
    is still being checked beyond the top-level activation status.
  - End-to-end UX: admin fills Business Details (business_type, address,
    city, state, pincode, bank) + adds at least one Stakeholder on
    `/admin/franchisees/[id]`, clicks "Start Razorpay onboarding" (creates
    linked account), then "Submit for KYC" (submits product config +
    bank). Razorpay's review team then advances the account through
    `under_review` → `activated`; our `handle_account_webhook` catches
    the transitions.
  - **Outbound API audit log (`razorpay_api_log` table)**: every mutating
    onboarding-chain SDK call (account / stakeholder / product create /
    edit / delete) flows through `RazorpayService._audit_call`, which
    captures request + response body + status + error message into the
    `razorpay_api_log` table. PII (`pan`, `account_number`, `ifsc_code`,
    `aadhaar`, `gst`, `gstin`, `tan`, `card_number`) is masked to
    `***LAST4` via `_mask_sensitive` before persistence. Read-only
    fetches and high-frequency calls (transfers, refunds, payments, QR)
    are intentionally NOT logged. Audit-write failures are swallowed so
    SDK call behaviour is preserved. Counterpart of the inbound
    `webhook_event` table — together they give end-to-end traceability
    for any Razorpay-side dispute. Joinable to `franchisee` via
    `franchisee_id` FK with `ON DELETE SET NULL` (logs survive franchisee
    deletion).
  - **Hard-delete a Razorpay linked account**: admins can permanently
    delete a stuck/misconfigured Razorpay account via the destructive
    "Delete Razorpay" button on `/admin/franchisees/[id]`. The
    confirmation dialog requires typing the exact `acc_*` ID. Backend
    refuses if any `CommissionLedgerEntry` exists for the franchisee
    (no force flag — fund-flow integrity). Idempotent on already-cleared
    state and tolerant of Razorpay 404s (account already gone upstream).
    Endpoint: `DELETE /api/admin/franchisees/{id}/razorpay-account`,
    orchestrated by `FranchiseeOnboardingService.delete_linked_account`.
    Razorpay DELETE first, then local cleanup inside `@in_transaction()`:
    deletes `franchisee_stakeholder` rows, clears all `razorpay_*` /
    `kyc_*` / `activated_at` fields, resets `status` to `DRAFT`.
  - **`FranchiseeResponse` financial rollup fields** — `total_invoiced`
    and `total_transferred` (Decimal, serialised as string) are added to
    the response on `GET /api/admin/franchisees` (list) and
    `GET /api/admin/franchisees/{id}` (detail). `total_invoiced` =
    `SUM(GSTInvoice.total_amount)` for the franchisee (gross incl. GST,
    no status filter — invoices are issued on creation).
    `total_transferred` = `SUM(CommissionLedgerEntry.franchisee_payout)`
    filtered by `settlement_status IN (TRANSFER_PROCESSED, SETTLED)` —
    money actually moved, excluding pending/failed/on-hold. List
    endpoint batches both aggregations via group-by to avoid N+1; detail
    endpoint runs single-id sums. Surfaced as two table columns on
    `/admin/franchisees` and two overview cards on
    `/admin/franchisees/[id]` (formatted with `formatINR`).
- **`franchisee_settlement_service.py`** - **Post-session franchisee payout**
  - `process_settlement(transaction_id)` runs from `transaction_finalizer`
    right after `process_qr_session_billing` returns (refund already
    issued). Creates a `CommissionLedgerEntry` with `idempotency_key=
    f"txn_{id}"` capturing the gross → net → franchisee_payout split.
    If `franchisee_payout < MINIMUM_TRANSFER_AMOUNT` (₹1) the entry is
    marked `BELOW_THRESHOLD` (terminal — retry sweep ignores it).
    Otherwise calls `initiate_transfer` if the franchisee is ACTIVE
    with a linked account.
  - `calculate_settlement(...)` is the pure math: `net_excl_gst =
    gross - refund - pg_fee - gst_collected`; `platform_commission =
    net_excl_gst × commission_pct`; `franchisee_earning = net_excl_gst
    − platform_commission`; **`tds_amount = franchisee_earning ×
    tds_pct`** (TDS base is post-commission, not net_excl_gst, so
    we don't over-withhold on platform's own income); `franchisee_payout
    = franchisee_earning − tds_amount`. `transfer_fee` is NOT deducted
    at calc time — it's populated after the fact from the
    `settlement.processed` webhook (Razorpay's actual per-transfer fee).
  - `initiate_transfer(entry)` enforces a **24-hour cooling period**
    after `franchisee.activated_at` (Razorpay rejects transfers within
    24h of activation). Within the window the entry is parked as
    `ON_HOLD` with `failure_reason="cooling_period"` and picked up by
    `retry_failed_transfers` later. Otherwise calls
    `razorpay_service.create_transfer` with a stable idempotency key
    (the ledger entry's `idempotency_key`) so retries are safe.
    Skips + marks `ON_HOLD` when `franchisee.transfers_enabled=False`
    or `funds_on_hold=True` (admin-driven gates today — see the
    onboarding service notes).
  - `handle_transfer_webhook(event_type, transfer_data)` handles only
    `transfer.processed` and `transfer.failed`. Razorpay does not
    emit `transfer.reversed` (reversals are reflected in the transfer
    entity's `amount_reversed` / `status` fields) or `transfer.settled`
    (that's `settlement.processed`).
  - `handle_settlement_webhook(event_type, settlement_data)` processes
    `settlement.processed` — when money lands in the franchisee's
    bank. Walks the settlement entity's `transfers` list (accepts
    either `[id, id, ...]` or `[{id, fees, tax}, ...]`), flips each
    matching `CommissionLedgerEntry` to `SETTLED`, stamps `settled_at`,
    and captures the per-transfer `transfer_fee` when available.
  - `retry_failed_transfers(franchisee_id=None)` background-job entry
    point. Picks up entries in both `FAILED` and `ON_HOLD` states
    (below `MAX_TRANSFER_RETRIES`) and re-runs `initiate_transfer`.
    Triggered from the franchisee admin "Retry failed settlements"
    endpoint.
  - Config: `MINIMUM_TRANSFER_AMOUNT=1.00`, `MAX_TRANSFER_RETRIES=3`.
    `RAZORPAY_TRANSFER_FEE_PERCENT` is **removed** — was double-charging
    the franchisee on top of Razorpay's own fee.

- **`routers/admin_settlements.py`** — admin operations across all franchisees' settlements.
  - `GET /api/admin/settlements/stuck` — paginated list of entries the `StuckPayoutDetector` flags (predicate shared via `build_stuck_filter`).
  - `POST /api/admin/settlements/{entry_id}/mark-below-threshold` — terminal-resolves a sub-floor `PENDING/FAILED/ON_HOLD` row to `BELOW_THRESHOLD`. Server validates `franchisee_payout < MIN_TRANSFER_AMOUNT` (422 otherwise). Idempotent.
  - `POST /api/admin/settlements/{entry_id}/mark-settled` — terminal-resolves to `SETTLED` for out-of-band resolutions (e.g. bank-transferred manually). Body: `{ note: str, min_length=3 }`. Sets `settled_at = now()` on first call only — idempotent re-clicks preserve the original timestamp; Razorpay ID fields untouched. Allowed source statuses: `PENDING/TRANSFER_INITIATED/TRANSFER_PROCESSED/FAILED/ON_HOLD`.
  - Both actions log a distinct `audit_log` `action` (`settlement.mark_below_threshold` / `settlement.manual_settle`). Per **ADR 0007**, there is no `MANUAL_SETTLED` enum value or `manual_resolution_note` column — the audit log is the system of record for who-resolved-what-when-and-why.
  - Frontend: `/admin/settlements/stuck` and the per-franchisee Settlement Ledger card both render the shared `components/SettlementTerminalActions.tsx` per row (eligibility-aware icon buttons + confirmation dialog with note textarea for the SETTLED action).

### Frontend Core (`/frontend/`)
- **`app/page.tsx`** - Role-based dashboard (different for ADMIN vs USER)
- **`app/admin/`** - Complete admin interface for station/charger/user management
  - **`app/admin/qr-codes/page.tsx`** - **NEW** QR code list with create/close actions, revenue stats
  - **`app/admin/qr-codes/[id]/page.tsx`** - **NEW** QR detail with payment history, refund tracking, QR image
- **`app/my-charges/page.tsx`** + **`app/my-charges/_components/`** - Public (no auth) page with charger map + transaction history. **Component split (2026-05-21)**: `page.tsx` is the composition shell (~455 lines); the active-session card, transaction card, refund-lifecycle pill, and charger-row are extracted into `_components/`. Top section: Leaflet map showing all stations with real-time availability (color-coded markers), user location, popup details, "Get Directions" to Google Maps. **Station detail modal** renders one row per **plug type** under a "Chargers" heading, each row showing 3-bucket status (Ready / In use / Out of service) and per-plug-type all-in tariff, with one "all prices include GST & fees" footnote. Faulted/Unavailable/Reserved collapse into "Out of service". Bottom section: UPI ID lookup for paginated QR transactions; refund pill renders the **3-state lifecycle from ADR 0005** (Initiated / Sent to bank / Failed) with speed-conditional wording derived from `razorpay_refund_speed_processed`. **Active session card (ADR 0006)**: above the status filter, a live-polled `ActiveSessionCard` stack renders the customer's in-progress QR sessions in one of 4 sub-states (Waiting / Charging / Paused / Stopping) with energy delivered, spent so far, refund-if-stopped-now, power draw, duration (client-side 1s tick via the shared `useNowTick` singleton clock in `lib/hooks/useNowTick.ts` — N cards = 1 timer), and a budget bar. **First-load skeleton + retry-able error banner** for the active-sessions query. **Adaptive polling**: 15s when at least one session is active, 60s when empty, paused entirely when the tab is hidden. Read-only — no remote-stop button (VPA is not a credential). **VPA persistence**: pre-fills from `localStorage["voltlync.myCharges.lastVpa"]` on mount (with one-time migration from the pre-namespacing `voltlync.lastVpa` key) but does NOT auto-search; persists on successful search; cleared on `Change`. **Waiting-state copy** reads `stale_threshold_seconds` from the API to render a specific auto-refund-window message.
- **`components/StationMap.tsx`** - Shared Leaflet map component (moved from `app/stations/`), used by both `/stations` and `/my-charges` pages
  - **`app/admin/users/[id]/transactions/page.tsx`** - User charging transaction history
  - **`app/admin/users/[id]/wallet/page.tsx`** - Wallet transaction history with running balance
  - **`app/admin/firmware/page.tsx`** - Firmware management dashboard
    - Upload firmware files with version and description
    - Real-time update status monitoring (10s auto-refresh)
    - Summary cards (pending, downloading, installing, completed, failed)
    - Firmware library with delete capability
  - **`app/admin/chargers/[id]/page.tsx`** - Charger detail with **firmware update, reset, signal quality & error history**
    - Current firmware version display
    - Update firmware button (disabled if offline)
    - Firmware version selection dialog
    - Recent update history (last 3 updates)
    - **Reset charger button** with Hard/Soft selection dialog
    - Visual warning for Hard reset during active charging
    - Reset button disabled if charger offline
    - **Real-time signal quality badge** (Good/Fair/Poor/Unknown)
    - RSSI display with color-coding (auto-refresh every 5s)
    - **NEW**: Latest error display with error code + vendor error code badges
    - **NEW**: Error history table (last 7 days) with resolution status
- **`app/stations/page.tsx`** - Interactive map with React Leaflet 5.0.0 for station discovery
- **`app/scanner/page.tsx`** - QR code scanner using ZXing 0.21.3
- **`app/my-sessions/page.tsx`** - **NEW** Combined user sessions (charging + wallet) with recharge button
- **`middleware.ts`** - Route protection and role-based redirects
- **`components/RoleWrapper.tsx`** - RBAC components (AdminOnly, UserOnly, AuthenticatedOnly)
- **`components/MeterValuesChart.tsx`** - Energy visualization with Recharts 3.2.1
- **`components/WalletRechargeModal.tsx`** - **NEW** Razorpay payment integration for wallet recharge

### **NEW**: Mobile App (`/app/`)
- **`src/App.tsx`** - Capacitor app root with Clerk provider and QueryClient setup
- **`src/routes.tsx`** - React Router with route prefetching for performance
- **`capacitor.config.ts`** - Capacitor configuration (App ID: com.lyncpower.user)
- **`android/`** - Native Android project with permissions configured
- **`ios/`** - Native iOS project with Info.plist permissions

### Mobile App Screens (`/app/src/screens/`)
- **`HomeScreen.tsx`** - Welcome screen with quick actions and "How to charge" guide
- **`StationsScreen.tsx`** - Interactive Leaflet map with:
  - Real-time station data with geolocation
  - Distance calculation (Haversine formula)
  - Color-coded markers (green=available, red=full)
  - Station details bottom sheet with Google Maps directions
- **`ScannerScreen.tsx`** - QR code scanner using `@capacitor/barcode-scanner`
  - Camera permission handling
  - Manual alphanumeric input fallback
- **`ChargeScreen.tsx`** - Live charging session with:
  - Real-time status updates (2-3s refresh)
  - Live meter values (energy, power, voltage, current)
  - Remote start/stop charging
  - Session duration timer and estimated cost
- **`SessionsScreen.tsx`** - Combined transaction history:
  - Charging sessions + wallet transactions merged
  - Wallet balance with Razorpay recharge integration
  - Pull-to-refresh
- **`SignInScreen.tsx`** - Clerk authentication flow

### Mobile App Components (`/app/src/components/`)
- **`ErrorBoundary.tsx`** - **NEW** - Comprehensive error handling for mobile
- **`Layout.tsx`** - **NEW** - Bottom tab navigation + header with user info
- **`Modal.tsx`** - **NEW** - Portal-based modal optimized for mobile
- **`NetworkStatus.tsx`** - **NEW** - Network connectivity indicator
- **`PullToRefresh.tsx`** - **NEW** - Pull-to-refresh gesture component
- **`SessionsSkeleton.tsx`** & **`StationsSkeleton.tsx`** - **NEW** - Loading states

### Mobile App Hooks (`/app/src/hooks/`)
- **`useNetworkStatus.ts`** - **NEW** - Track network connectivity via Capacitor
- **`usePullToRefresh.ts`** - **NEW** - Pull-to-refresh gesture handling
- **`useStatusBar.ts`** - **NEW** - Native status bar control

### Native Integrations
- **Capacitor Plugins**:
  - `@capacitor/barcode-scanner` v2.2.0 - QR code scanning
  - `@capacitor/geolocation` v7.1.5 - GPS location for station finder
  - `@capacitor/network` v7.0.2 - Network status detection
  - `capacitor-razorpay` v1.3.0 - Native payment SDK integration
- **Permissions Configured**:
  - iOS: Camera (QR), Location (station finder) in Info.plist
  - Android: Camera, Location, Internet, Network State in AndroidManifest.xml

### API Integration (`/frontend/lib/`)
- **`api-client.ts`** - Base HTTP client with automatic Clerk JWT injection
- **`api-services.ts`** - Domain-specific services (stations, chargers, users, transactions, **wallet payments, firmware**)
  - **`walletPaymentService`** - **NEW** Razorpay payment API methods
    - `createRechargeOrder()` - Create payment order
    - `verifyPayment()` - Verify payment completion
    - `getPaymentStatus()` - Check payment status
    - `getRechargeHistory()` - Get recharge history
  - **`firmwareService`** - **Firmware management API methods**
    - `uploadFirmware()` - Upload firmware file (FormData)
    - `getFirmwareFiles()` - List firmware with pagination
    - `deleteFirmwareFile()` - Soft delete firmware
    - `triggerUpdate()` - Single charger update
    - `bulkUpdate()` - Multiple chargers update
    - `getFirmwareHistory()` - Update history per charger
    - `getUpdateStatus()` - Real-time dashboard status
  - **`chargerService`** - **Charger control API methods**
    - `remoteStart()` - Start charging remotely
    - `remoteStop()` - Stop charging remotely
    - `changeAvailability()` - Change charger availability
    - `reset()` - Reset charger (Hard/Soft)
  - **`signalQualityService`** - **Cellular signal quality monitoring**
    - `getSignalQuality()` - Get history with time filtering
    - `getLatestSignalQuality()` - Get most recent reading
  - **`chargerErrorService`** - **NEW** - Charger error history and diagnostics
    - `getErrors()` - Get error history with filters (hours, include_resolved, limit)
    - `getLatestError()` - Get most recent unresolved error
- **`queries/`** - TanStack Query hooks with optimized caching strategies
  - **`qr-codes.ts`** - **NEW** QR code management hooks
    - `useQRCodes(params)` - List with filters (30s stale)
    - `useQRCode(id)` - Detail (10s stale)
    - `useQRCodeByCharger(chargerId)` - Charger-specific QR (30s stale)
    - `useQRPayments(qrId, params)` - Paginated payments (10s stale)
    - `useCreateQRCode()` - Creation mutation
    - `useCloseQRCode()` - Close mutation
  - **`users.ts`** - User transaction and wallet query hooks
  - **`firmware.ts`** - Firmware TanStack Query hooks
    - `useFirmwareFiles()` - Query firmware files (30s stale time)
    - `useUploadFirmware()` - Upload mutation
    - `useDeleteFirmware()` - Delete mutation
    - `useTriggerUpdate()` - Single update mutation
    - `useBulkUpdate()` - Bulk update mutation
    - `useFirmwareHistory()` - Update history query (10s stale)
    - `useUpdateStatus()` - Dashboard status (5s stale, **10s auto-refresh**)
  - **`chargers.ts`** - **Charger control & monitoring hooks**
    - `useChargers()`, `useCharger()`, `useChargerByStringId()` - CRUD queries
    - `useRemoteStart()` - Remote start mutation
    - `useRemoteStop()` - Remote stop mutation
    - `useResetCharger()` - Reset charger mutation (Hard/Soft)
    - `useChangeAvailability()` - Availability toggle mutation
    - `useLatestSignalQuality()` - Latest reading (5s stale, **5s auto-refresh**)
    - `useChargerErrors()` - Error history (30s stale, **30s auto-refresh**)
  - **`logs.ts`** - Charger log and audit trail hooks
    - `useChargerLogs()` - OCPP message logs (IN/OUT)
    - `useChargerLogSummary()` - Log summary stats
    - `useChargerTimeline()` - Charger event timeline
    - `useEntityAuditLogs()` - Entity audit log history
  - **`dashboard.ts`** - Admin dashboard hooks
    - `useDashboardStats()` - Total stations, chargers, availability, active sessions
    - `useDashboardRefresh()` - Dashboard data refresh
  - **`public-stations.ts`** - Public station discovery hooks (unauthenticated)
    - `usePublicStations()` - List stations with charger availability
    - `usePublicStation()` - Single station detail
- **`csv-export.ts`** - CSV export utility for transaction data
- **`newrelic-browser.ts`** - New Relic browser agent configuration
- **Frontend Sentry** — `@sentry/nextjs` 10.x, errors-only setup (no perf, no Replay) added 2026-05-25 to complement NR Browser. Configs: `instrumentation-client.ts` (browser SDK init), `sentry.server.config.ts` (Node SSR / Server Actions), `sentry.edge.config.ts` (middleware.ts runtime), `instrumentation.ts` (per-runtime loader + `onRequestError`), `app/global-error.tsx` (React render-error capture for App Router). `next.config.ts` wraps via `withSentryConfig` for source-map upload — uploads occur at build time when `SENTRY_AUTH_TOKEN` is set, otherwise silently skipped. Runtime guard: each `Sentry.init` is wrapped in `if (dsn)` so missing `NEXT_PUBLIC_SENTRY_DSN` no-ops cleanly in dev. Required env vars (all build-time, baked into client bundle): `NEXT_PUBLIC_SENTRY_DSN`, `NEXT_PUBLIC_SENTRY_ENVIRONMENT`, and the source-map upload trio `SENTRY_ORG` / `SENTRY_PROJECT` / `SENTRY_AUTH_TOKEN`. Two separate Sentry projects exist in the `idofthings` org: `ocpp-backend` (FastAPI, environment tag separates staging vs prod) and `ocpp-frontend` (Next.js, same pattern). NR Browser still captures errors + Web Vitals + distributed traces back to backend NR app; Sentry is the better-triage layer on top.
- **`contexts/AuthContext.tsx`** - Clerk auth wrapper with `isAuthReady`, `getToken`, global token access
- **`contexts/QueryClientProvider.tsx`** - TanStack Query setup
- **`contexts/ThemeContext.tsx`** - Light/dark/system theme management

### Key Configuration
- **`backend/requirements.txt`** - Python dependencies (FastAPI, python-ocpp, Tortoise ORM, etc.)
- **`frontend/package.json`** - Node dependencies (Next.js 15, React 19, Clerk, TanStack Query, etc.)
- **`backend/pyproject.toml`** - pytest configuration and Aerich migration settings

---

## Database tier (post-2026-05-28 prod RDS cutover)

Both staging and prod are on AWS RDS Postgres in `ap-south-1` as of 2026-05-28. Local dev remains Docker postgres.

- **Local dev**: Docker postgres in `docker-compose.yml`. No SSL. `make local-db-reset` is the canonical fresh-start path.
- **Staging**: **AWS RDS Postgres at `ocpp-staging-db.c1608qm4i94k.ap-south-1.rds.amazonaws.com`**. Single-AZ `db.t4g.micro` in `ap-south-1c` (EC2 is in `ap-south-1a` — cross-AZ ~1ms per query). 20GB gp3 with auto-scaling to 100GB. 14-day automated backups + 5-min PITR. TLS `verify-full`. The local Docker postgres in `docker-compose.staging.yml` is the rollback target for the 14-day validation window. Cutover via `.scratch/rds-staging-migration/`.
- **Prod**: **AWS RDS Postgres at `ocpp-prod-db.c1608qm4i94k.ap-south-1.rds.amazonaws.com`**. Single-AZ `db.t4g.small` in `ap-south-1a` (same-AZ as prod EC2 — sub-ms latency). 50GB gp3 with auto-scaling to 200GB. **30-day** automated backups + 5-min PITR. Performance Insights enabled (31-day retention). Deletion-protection on. TLS `verify-full`. Cutover via `.scratch/rds-prod-migration/` on 2026-05-28 09:30Z with **4 min customer-visible downtime** (well under the 10-15 min PRD budget — DB was small post-cleanup at 117 MB custom-format dump). Docker postgres in `docker-compose.prod.yml` remains the rollback target through the **28-day** validation window (longer than staging because prod rollback cost is higher). Decommission triggers + checklist live in `.scratch/rds-prod-migration/PRD.md`.

Both RDS instances started single-AZ for cost (-$35/mo vs Multi-AZ). Upgrade either to Multi-AZ via `aws rds modify-db-instance --db-instance-identifier ocpp-{env}-db --multi-az --apply-immediately` — zero downtime, ~5 min.

### SSL config (`backend/db_ssl.py`)

Single `get_ssl_config()` helper drives all three DB-connect call sites — runtime (`database.py`), Aerich (`tortoise_config.py`), and the entrypoint pre-flight loop (`docker-entrypoint.sh`). Don't add a 4th call site without using this helper. Env-var contract:

- `DB_SSL_MODE=` (empty) → legacy fallback: `disable` for local/Docker hosts, `require` otherwise. Local dev uses this.
- `DB_SSL_MODE=verify-full` → TLS with CA validation. Required for RDS. **Both staging and prod use this.**
- `DB_SSL_MODE=verify-ca|require|prefer|allow|disable` → passthrough to asyncpg.

The AWS RDS global CA bundle is baked into the backend image at `/etc/ssl/rds-ca-bundle.pem` during `docker build` — no code or compose change when adding a new RDS instance, only `DB_HOST` + `DB_SSL_MODE` in the env file.

### Cutover learnings (feedback memory + applied to prod)

The prod cutover ran in 4 minutes because the staging cutover learnings were already absorbed:

- **The entrypoint pre-flight check has its own DB connection logic.** It hardcoded `ssl='disable'` and was missed in the initial staging issue 02 PR. Caused ~5 min of bonus downtime during the staging cutover. Already fixed before prod cutover. Always grep for ALL `asyncpg.connect` / `psycopg.connect` / `pg_isready` / `psql -h` call sites when changing DB connection config. See [[feedback-check-entrypoint-during-db-config-changes]].
- **RDS provisioning took ~26 min for prod** vs ~20 min for staging — likely due to Performance Insights enabled (deferred on staging). Plan ≥30 min for provisioning in any maintenance window.
- **`DROP DATABASE` requires ownership.** RDS master user is `rds_superuser`, not real superuser — can't drop a DB owned by another user. Use `DROP OWNED BY <app_user> CASCADE` as the app user instead.
- **Custom format (`-F c`) was used for prod**, plain SQL for staging. Both restored cleanly. Custom format is slightly faster and supports selective restore later (e.g., `pg_restore -t single_table`); use it for new cutovers by default.
- **`pg_dump -j 4` requires `-F d` (directory format), not `-F c`.** Trying `-F c -j 4` errors with "parallel backup only supported by the directory format". For single-file custom format, drop `-j`.
- **POSIX `/bin/sh` on Amazon Linux 2 doesn't tolerate parens in unquoted `echo` strings.** `echo --- step 2 (begins) ---` syntax-errors. Quote any echo containing parens. Bit us multiple times during prod cutover SSM scripts.
- **CSP allow-list is env-driven.** `CSP_CLERK_HOSTS` env var is read by nginx entrypoint envsubst — switch Clerk environments without editing nginx conf. See `nginx/prod.conf` + `nginx/staging.conf`. Worker-src + js-agent.newrelic.com are also explicitly allowed.

### Charger state — two orthogonal fields (post-2026-05-27)

The `charger` row carries **two state-shaped columns by design**, captured in **ADR 0008**:

- `latest_status` (`ChargerStatusEnum`): what the charger reports via OCPP `StatusNotification`. Written only by the `StatusNotification` handler in `main.py`. Read by the status pill, OCPP routing, billing logic.
- `availability` (`ChargerAvailabilityEnum`): what an admin or franchisee has commanded via `ChangeAvailability`. Written by the admin/franchisee endpoints on OCPP `Accepted`/`Scheduled`. Read by the admin UI toggle.

The two are independent — a `Faulted` charger can be admin-set `Operative`; a `Charging` charger that admin clicks `Inoperative` stays `Charging` (per OCPP `Scheduled` semantics) but flips `availability=Inoperative` immediately. The toggle was previously broken because it read `latest_status` as a proxy for both concerns; this stopped working any time a charger Accepted ChangeAvailability without sending a follow-up StatusNotification. See ADR 0008 for the full rationale and considered alternatives.

---

## Database Schema Quick Reference

### Core Tables with Relationships
```sql
-- User Management (Clerk Integration + UPI_GUEST)
user (id, clerk_user_id, phone_number, full_name, role, upi_vpa, auth_provider) -- USER/ADMIN roles, EMAIL/GOOGLE/CLERK/UPI_GUEST auth
wallet (id, user_id, currency) -- NO stored `balance` column post migration 33. Use `WalletService.get_balance(wallet_id)` — derives via SUM over the log, Redis-cached, invalidated on every WalletTransaction write.
-- Wallet sessions enforce an in-session balance cap mirroring QR's pattern. On StartTransaction the wallet's available balance is snapshotted into Redis (`wallet_session:{txn_id}`, paise-int). On every MeterValues frame `WalletSessionService.check_balance_and_auto_stop` recomputes accumulated cost; when cost ≥ snapshot it schedules `RemoteStopTransaction` via `safe_create_task` (never awaits — would deadlock the OCPP CALLRESULT). Idempotency flag in the payload prevents duplicate stops. DB-fallback rebuild reads balance via `WalletService.get_balance` so server restarts mid-session still honour the cap. Key deleted on StopTransaction.
-- **Internal-role wallet skip (ADR 0004, 2026-05-19)**: ADMIN- and FRANCHISEE-initiated sessions are *operational*, not customer-facing. `WalletService.process_transaction_billing` and `WalletSessionService.cache_session_on_start` short-circuit early via `core.roles.INTERNAL_ROLES` — no CHARGE_DEDUCT row, no GST invoice (`invoice_service.py` already skipped), no budget cap. Sessions are marked COMPLETED with a `transaction.status_changed` audit row carrying `trigger="InternalRoleSkip"`. Metrics: `Custom/Wallet/InternalRoleSkipped`, `Custom/WalletSession/InternalRoleSkipped`. Fixes the user-12 retry-storm pattern where admin test-charges sat in BILLING_FAILED forever because the wallet had been deleted by a backfill.
-- **Internal-role wallet creation gate (ADR 0004, 2026-05-19)**: `routers/webhooks.py:handle_user_created` only calls `Wallet.create(user=user)` when `user_role not in INTERNAL_ROLES`. The runtime skip above is the defense; this is the prevention. The existing-user branch never created a wallet, so the previous user-12 retry storm came specifically from new ADMIN/FRANCHISEE arrivals via Clerk. One-shot SQL cleanup ran 2026-05-19 on dev (2 rows: user IDs 2, 8) and staging (9 rows: user IDs 12, 16, 19, 20, 22, 23, 24, 31, 39). Prod cleanup pending the next deploy of `deploy` branch.
-- **Zero-energy watchdog Decimal serialization (fix 2026-05-20)**: `MeterValues` parser constructs `reading_kwh` as a `Decimal`; the watchdog now coerces it to `float` at the entry point so the `set_zero_energy_state` payload is JSON-safe. As a secondary defense, all four `json.dumps(data)` writes in `redis_manager.py` (`set_qr_session`, `set_wallet_session`, `set_zero_energy_state`, `set_socket_grace_period`) now use `default=str`. Before the fix, staging logged 223 `Object of type Decimal is not JSON serializable` errors over a recent window — every MeterValues frame of every active session — and the watchdog state never persisted, leaving stall detection silently disabled for affected transactions.
wallet_transaction (id, wallet_id, amount, type, payment_metadata) -- `amount` is always >= 0; direction carried by `type` (TOP_UP credits, CHARGE_DEDUCT debits). Enforced by `WalletTransaction.save()` validator + DB CHECK `wallet_transaction_amount_non_negative` (migration 32 NOT VALID, redeemed to VALID by migration 33). Only TOP_UP rows with `payment_metadata->>status = 'COMPLETED'` contribute to derived balance; PENDING/FAILED rows are filtered out. Migration 33 inserted "BALANCE_ADJUSTMENT" rows (description-tagged) to absorb any pre-existing stored-vs-derived drift.

-- Charging Infrastructure
charging_station (id, name, latitude, longitude, address)
charger (id, charge_point_string_id, station_id, vendor, model, latest_status, last_heart_beat_time)
connector (id, charger_id, connector_id, connector_type, max_power_kw) -- connector_type: Type2, CCS, CHAdeMO, Socket
tariff (id, charger_id, rate_per_kwh, tariff_per_kwh_all_in, gst_percent, hsn_sac_code, is_global) -- ADR 0003
-- `tariff_per_kwh_all_in` DECIMAL(10,4) — operator-typed, customer-displayed all-inclusive rate (incl. GST + synthetic 2% gateway fee). Authoritative for display. Added 2026-05-18 via migration 36; backfilled from `rate_per_kwh × (1 + gst_percent/100)` so customer-facing prices were preserved.
-- `rate_per_kwh` DECIMAL(8,4) — internal back-derived rate (`all_in × 0.98 / 1.18`), used only by line-item billing math. NEVER customer-facing post-2026-05-18. Migration 36 shrunk every existing value by 2% so the back-calc identity holds; franchisees absorb the margin until they re-enter via the new API.
-- 4dp precision on per-kWh rates avoids 1-paise truncation compounding across kWh. Amount/total columns stay at 2dp (the paisa).

-- OCPP Transactions
transaction (id, user_id, charger_id, start_meter_kwh, end_meter_kwh, transaction_status, suspended_at, resumed_at, resume_count, energy_charge, gst_amount, gst_rate_percent, total_billed)
-- `gst_rate_percent` is snapshotted from the tariff at billing time so invoices stay stable if the tariff later changes.
-- `start_meter_kwh`, `end_meter_kwh`, `energy_consumed_kwh` stored as DECIMAL(12,3) — OCPP reports Wh-resolution readings (3dp kWh). Migrated from FloatField in migration 31 to eliminate binary-float noise on energy × rate multiplications.
meter_value (id, transaction_id, reading_kwh, current, voltage, power_kw)
-- `reading_kwh` is DECIMAL(12,3); raw OCPP MeterValues are parsed via `Decimal(str(value))` to preserve exact decimal representation through the Wh→kWh conversion.

-- Firmware Management
firmware_file (id, version, filename, file_path, file_size, checksum, description, uploaded_by, is_active)
firmware_update (id, charger_id, firmware_file_id, status, download_url, started_at, completed_at, error_message)

-- Signal Quality Monitoring
signal_quality (id, charger_id, rssi, ber, timestamp, created_at) -- Cellular signal metrics via DataTransfer

-- Charger Error Tracking
charger_error (id, charger_id, connector_id, status, error_code, vendor_error_code, vendor_id, info, error_timestamp, is_resolved, resolved_at) -- OCPP StatusNotification errors

-- QR-Based Appless Payments (NEW)
charger_qr_code (id, charger_id, razorpay_qr_code_id, image_url, short_url, is_active) -- Razorpay UPI QR codes
qr_payment (id, charger_id, charger_qr_code_id, user_id, transaction_id, razorpay_payment_id, amount_paid, customer_vpa, customer_name, customer_contact, energy_cost, gst_amount, platform_fee, razorpay_commission, razorpay_gst, fee_source, refund_amount, razorpay_refund_id, status, failure_reason, metadata) -- Payment lifecycle with actual Razorpay fee tracking

-- GST Invoicing (customer-facing tax invoice per session)
-- VoltLync is the GST supplier on every invoice (merchant-of-record under Razorpay Route).
-- Each franchisee operates as a substore — snapshot identity on the invoice, per-franchisee numbering, "Operated by" block on PDF (Razorpay payer-payee transparency rule).
gst_invoice_counter (id, franchisee_id, series, financial_year, last_number) -- One row per (franchisee, series, FY); NULL franchisee = VoltLync-owned. Restored in migration 29.
gst_invoice (id, invoice_number, series, financial_year, transaction_id, franchisee_id, user_id, supplier_name, supplier_gstin, supplier_state_code, franchisee_business_name, franchisee_gstin, franchisee_address, franchisee_state, franchisee_state_code, customer_name, customer_identifier, station_name, place_of_supply_state_code, charger_id_str, energy_consumed_kwh, tariff_rate_incl_tax, hsn_sac_code, gst_rate_percent, energy_taxable_value, gateway_charges, gateway_hsn_code, total_taxable_value, is_inter_state, cgst_rate, cgst_amount, sgst_rate, sgst_amount, igst_rate, igst_amount, total_tax, total_amount, amount_in_words, payment_method, transaction_amount, refund_amount, pdf_url)
-- `series` = 'WAL' (wallet) or 'QR' (UPI guest).
-- invoice_number format: VL/F{franchisee_id}/{SERIES}/{FY_NODASH}/{SEQ:05d} for franchisee-owned, VL/{SERIES}/{FY_NODASH}/{SEQ:05d} for VoltLync-owned.
-- `transaction_amount` is the gross UPI payment; `refund_amount` is what was returned to the customer (NULL/0 for wallet sessions).
-- `franchisee_*` snapshot columns drive the "Operated by:" block on the PDF; NULL for VoltLync-owned stations (block is omitted).
-- `energy_consumed_kwh` on the invoice is the BILLABLE kWh after the QR cap fix — not the raw meter reading on transaction.energy_consumed_kwh.
-- `pdf_url` holds an S3 object key, populated lazily on first download (presigned URL served at /api/.../pdf endpoints).
-- Invoice generation is blocked at the service layer when VOLTLYNC_GSTIN env var is empty (CGST Rule 46).
-- Invoice generation is also skipped when `Transaction.user.role` is ADMIN or FRANCHISEE — those sessions are operational (test/courtesy/own-station remote-starts) and do not produce customer-facing sales. Skip increments `Custom/Invoice/InternalRoleSkipped`; no invoice number is consumed.
-- Cancellation infrastructure was removed: invoices are immutable once issued.
-- Credit notes are not modelled today; revisit if/when B2B (ITC-claiming customers) is introduced.

-- Audit & Webhooks
audit_event (id, event_type, entity_type, entity_id, details, created_at) -- System audit trail
webhook_event (id, provider, event_type, payload, processed, created_at) -- Webhook history

-- System Logging
log (id, charge_point_id, direction, payload, correlation_id) -- All OCPP messages
```

### Important Enums
- **`ChargerStatusEnum`**: OCPP 1.6 statuses (Available, Charging, Unavailable, Faulted, etc.)
- **`TransactionStatusEnum`**: Complete lifecycle (STARTED, PENDING_START, RUNNING, SUSPENDED, PENDING_STOP, STOPPED, COMPLETED, CANCELLED, FAILED, BILLING_FAILED)
- **`QRPaymentStatusEnum`**: PAID, CHARGING, COMPLETED, REFUNDED, REFUND_FAILED, EXPIRED, FAILED
- **`AuthProviderEnum`**: EMAIL, GOOGLE, CLERK, UPI_GUEST
- **`FirmwareUpdateStatusEnum`**: PENDING, DOWNLOADING, DOWNLOADED, INSTALLING, INSTALLED, DOWNLOAD_FAILED, INSTALLATION_FAILED, CANCELLED
- **`UserRoleEnum`**: USER and ADMIN for role-based access control
- **`WebhookSourceEnum`**: CLERK, RAZORPAY for webhook event logging

---

## OCPP 1.6 Implementation Details

### Message Handlers in `main.py`

**Core OCPP Messages Implemented**:
1. **BootNotification** - Charger registration with 30s heartbeat interval, **suspends ongoing transactions** (SUSPENDED status with `suspended_at` timestamp) for possible resume; auto-stops after `SUSPEND_TIMEOUT_SECONDS` (default 300s) with wallet billing + QR billing/refund. `@after('BootNotification')` hook pushes PostBootState DataTransfer with meter value + pending transaction info.
2. **Heartbeat** - Connection liveness (90s timeout)
3. **StatusNotification** - Updates charger.latest_status + **error tracking with vendor codes** + **transaction failure detection** + **socket charger grace period**
   - Captures standard OCPP error codes (GroundFailure, HighTemperature, etc.)
   - Captures vendor-specific error codes (vendorErrorCode field)
   - Stores errors in `charger_error` table with resolution tracking
   - Auto-resolves errors when "NoError" status received
   - **Transaction failure detection**: If status transitions to a non-charging state while a transaction is RUNNING, behavior depends on connector type:
     - **Type 2/CCS/CHAdeMO**: Immediately fails transaction with billing + QR refund
     - **Socket chargers**: `Available` status triggers a 5-minute grace period (`SOCKET_GRACE_PERIOD_SECONDS`) via Redis. If MeterValues arrive during grace, transaction stays alive. If not, transaction fails after timeout.
     - `Faulted`/`Unavailable`/`Reserved` always fail immediately regardless of connector type
   - Charging states (no auto-fail): `Charging`, `Preparing`, `SuspendedEVSE`, `SuspendedEV`, `Finishing`
4. **StartTransaction** - Creates Transaction with RUNNING status + **links QR payment** via `QRPaymentService.link_transaction_to_qr_payment()` (caches budget in Redis)
5. **StopTransaction** - Finalizes transaction with automated billing via WalletService + **QR billing** via `QRPaymentService.process_qr_session_billing()` (calculates cost, issues refund). **Invalid stop reasons** (e.g., firmware sending non-standard values like `"AppStop"`) are sanitized to `"Other"` via `route_message` override to prevent OCPP validation rejection
6. **MeterValues** - Stores real-time energy data (kWh, current, voltage, power) + **QR budget check** via `QRPaymentService.check_budget_and_auto_stop()` (schedules RemoteStop if budget exceeded)
7. **FirmwareStatusNotification** - **Firmware update progress tracking**
   - Maps OCPP status (Downloading → Downloaded → Installing → Installed) to database
   - Updates FirmwareUpdate record with timestamps and status
   - On success: Updates charger.firmware_version field
   - On failure: Stores error message
   - Complete audit logging for compliance
8. **DataTransfer** - **Vendor-specific data messages**
   - Handles custom data from charge points (vendor-specific extensions)
   - **JET_EV1 Signal Quality data**: Validates and stores RSSI (0-31, 99=unknown) and BER (0-7, 99=unknown) in `signal_quality` table
   - **GetLastMeterValue**: Transaction resume support — charger requests last meter reading for a transaction ID, server responds with the last known kWh reading so the charger can resume from the correct point
   - **PostBootState (server→charger)**: After BootNotification, pushes `{hasPendingTransaction, lastMeterValueWh, transactionId}` via `@after` hook. Charger resumes by sending MeterValues or StopTransaction.

**Remote Commands Supported**:
- `RemoteStartTransaction` - Start charging remotely (with double-prevention check)
- `RemoteStopTransaction` - Stop charging remotely
- `ChangeAvailability` - Set Operative/Inoperative
- **`UpdateFirmware`** - **Trigger OTA firmware update**
  - Sends download URL, retrieve date, retries, retry interval
  - Pre-validated: charger online, no active transaction
  - Tracked via FirmwareUpdate database record
- **`Reset`** - **Remote charger reboot (Hard/Soft)**
  - Hard: Complete reboot, stops all operations (blocked during active charging)
  - Soft: Graceful restart, may continue operations
  - Charger sends BootNotification after reset
- `DataTransfer` - VOLTLYNC PostBootState for post-reboot meter restore + transaction resume
  - Safety validation: Hard reset blocked if active transaction exists

### WebSocket Endpoint
- **URL**: `ws://localhost:8000/ocpp/{charge_point_id}` (development)
- **Authentication**: Validates charge_point_string_id exists in database
- **Logging**: All messages logged to `log` table with correlation IDs
- **Connection Management**: Redis tracks active connections with heartbeat monitoring

---

## QR-Based Appless Charging (Quick Reference)

### Payment Flow Summary
```
Customer scans UPI QR → Razorpay webhook (qr_code.credited) → User resolution (phone/VPA/UPI_GUEST)
→ RemoteStartTransaction (with retry) → Transaction linked → Budget cached in Redis
→ MeterValues budget check (auto-stop if exceeded) → StopTransaction → Calculate cost → Refund unused ₹
```

### Key Files
- `backend/services/qr_payment_service.py` - Core service (~600 lines)
- `backend/routers/qr_codes.py` - Admin CRUD endpoints
- `backend/routers/public_qr_transactions.py` - Public transaction history lookup by UPI ID
- `backend/routers/webhooks.py` - `qr_code.credited` webhook handler
- `backend/redis_manager.py` - `qr_session:{txn_id}` cache methods
- `frontend/app/admin/qr-codes/` - Admin UI pages
- `frontend/app/my-charges/page.tsx` - Public transaction history page (no auth)
- `frontend/lib/queries/qr-codes.ts` - TanStack Query hooks
- `frontend/lib/queries/public-qr-transactions.ts` - Public QR transaction lookup hook

### Redis Cache Structure
```
Key: qr_session:{transaction_id}
Value: {qr_payment_id, amount_paid, platform_fee, budget_limit, tariff_rate, gst_percent, start_meter_kwh, charger_id}
TTL: 86400s (24h)
```

### Error Handling Summary
| Scenario | Action |
|----------|--------|
| Duplicate payment_id | Skip (idempotent) |
| Payment >5min old | Refund (stale) |
| Charger already active | Refund (double-payment) |
| Charger disconnected | Refund |
| Plug-in timeout (5min) | Refund |
| RemoteStart fails (2 retries) | Refund |
| Budget exceeded during charging | Auto-stop via RemoteStop |
| Invalid StopTransaction reason | Sanitized to "Other", processed normally |
| Charger reboot (BootNotification) | Transaction suspended → auto-stop after 300s timeout with wallet billing + QR billing/refund |
| Charger sends GetLastMeterValue | Responds with last meter reading for seamless resume |
| Refund <₹1 | Absorbed (operator credit) |
| Redis cache miss | Rebuild from DB |
| Non-standard StopTransaction reason | Sanitized to "Other" via route_message override |
| Remote start already succeeded | Skip retry (double prevention) |
| Stale suspended transaction (>5h) | Auto-stopped by billing retry service |
| Orphaned QR payment (PAID, no txn) | Refunded by billing retry service |
| Failed QR refund (REFUND_FAILED) | Retried by billing retry service |

---

## Authentication & Role-Based Access Control

### Clerk Integration
**Backend Authentication**: `auth_middleware.py` - ClerkJWTBearer for JWT validation
**Frontend Authentication**: `middleware.ts` - Route-level protection and role redirects
**User Roles**: USER (default) and ADMIN with automatic role assignment via webhooks

### RBAC Implementation
**Route Protection**:
- `/api/admin/*` - Requires ADMIN role
- `/users/*` - Requires authentication (any role)
- `/auth/*` - Public endpoints

**Component-Level RBAC**:
```typescript
// frontend/components/RoleWrapper.tsx
<AdminOnly>Admin-only content</AdminOnly>
<UserOnly>User-only content</UserOnly>  
<AuthenticatedOnly>Authenticated user content</AuthenticatedOnly>
```

### User Experience by Role
**USER Role**:
- Dashboard with quick access to station finder and QR scanner
- Interactive station map (`/stations`) with real-time availability
- QR code scanner (`/scanner`) for charger access
- Personal charging history and wallet balance

**ADMIN Role**:
- Full system dashboard with real-time statistics
- Station management (`/admin/stations`) with CRUD operations
- Charger management (`/admin/chargers`) with OCPP remote commands
- User management (`/admin/users`) with transaction history and wallet control

---

## API Endpoints Quick Reference

### Admin APIs (`/api/admin/`)
```
Stations:
GET/POST /stations - List/create stations with geographic data
GET/PUT/DELETE /stations/{id} - Individual station operations

Chargers:
GET/POST /chargers - List/create chargers with real-time connection status + latest_error
GET/PUT/DELETE /chargers/{id} - Individual charger operations with latest_error
POST /chargers/{id}/remote-start - Send RemoteStartTransaction OCPP command
POST /chargers/{id}/remote-stop - Send RemoteStopTransaction OCPP command
POST /chargers/{id}/change-availability - Send ChangeAvailability OCPP command (can be sent at any time per OCPP 1.6)
POST /chargers/{id}/reset?type={Hard|Soft} - Send Reset OCPP command (Hard reset blocked during active charging)
GET /chargers/{id}/errors - **NEW** Error history with pagination (hours, include_resolved filters)
GET /chargers/{id}/errors/latest - **NEW** Latest unresolved error for charger

Transactions:
GET /transactions - List transactions with filtering and analytics summary
GET /transactions/{id} - Transaction details
GET /transactions/{id}/meter-values - Energy consumption data with chart data

GST Filings (admin window at /admin/gst-filings):
GET /invoices - Paginated invoice list with filters: financial_year, series (WAL|QR), franchisee_id, start_date/end_date (ISO 8601 with TZ, applied to invoice_date), place_of_supply_state_code, is_inter_state, q (free-text invoice number / customer). JSON response carries the full PDF-equivalent field set (tariff_rate_incl_tax, charged_on, duration_seconds, gateway_hsn_code, station_location, connector_type, supplier/customer addresses, amount_in_words) so the UI's expandable detail panel renders without extra calls.
GET /invoices/summary - Aggregate totals (count, taxable, CGST/SGST/IGST, total) over the same filtered set, plus by_series counts
GET /invoices/export.csv - Streaming CSV (text/csv, StreamingResponse) — one row per invoice; superset of UI columns including tariff/kWh, charged_on, duration_seconds, gateway HSN, station_location, connector_type, addresses, amount_in_words; respects all list filters
GET /invoices/{id}/pdf - Lazy S3 upload + presigned-URL redirect (302) for the customer-facing invoice PDF
UI: lean default columns (Invoice#, Date, Series, Customer, Operated by, HSN, kWh, Taxable ₹, GST %, CGST ₹, SGST ₹, IGST ₹, Total ₹, Refund ₹); click a row to expand a tally-friendly detail panel with PoS, station/charger/connector, charged-on, duration, tariff, energy + gateway line breakdowns, payment method, txn ₹, amount in words. PoS column intentionally removed from the main row.
```

### User APIs
```
GET /api/auth/me - Current user info from JWT
GET /auth/profile - User profile with role information

# Admin User Management
GET /users - List users (admin only) with pagination
GET /users/{id} - User profile details
GET /users/{id}/transactions - **NEW** User charging transactions (paginated)
GET /users/{id}/transactions-summary - **NEW** Transaction summary stats
GET /users/{id}/wallet - User wallet balance
GET /users/{id}/wallet-transactions - **NEW** Wallet transaction history with running balance
POST /users/{id}/deactivate - Soft delete user

# Current User APIs
GET /users/my-wallet - Current user's wallet balance
GET /users/my-sessions - **NEW** Current user's all transactions
```

### **NEW**: Wallet Payment APIs (`/api/wallet/`)
```
POST /wallet/create-recharge - Create Razorpay order for wallet recharge
  Request: { "amount": 500.00 }
  Response: { "order_id", "amount", "currency", "key_id", "wallet_transaction_id" }

POST /wallet/verify-payment - Verify payment from frontend callback
  Request: { "razorpay_order_id", "razorpay_payment_id", "razorpay_signature" }
  Response: { "success", "message", "wallet_balance", "transaction_id" }

GET /wallet/payment-status/{transaction_id} - Get payment transaction status
  Response: { "transaction_id", "amount", "status", "razorpay_order_id", ... }

GET /wallet/recharge-history - Get user's wallet recharge history
  Response: { "data": [...transactions], "total": N }
```

### **Firmware Management APIs** (`/api/admin/firmware/*` + `/api/firmware/*`)
```
# Admin Endpoints (require authentication)
POST /api/admin/firmware/upload - Upload firmware file (.bin, .hex, .fw)
  FormData: { file, version, description }
  Response: { id, version, filename, file_size, checksum, is_active, ... }

GET /api/admin/firmware - List firmware files with pagination
  Params: { page?, limit?, is_active? }
  Response: { data: [firmware_files], total, page, limit }

DELETE /api/admin/firmware/{id} - Soft delete firmware (sets is_active=False)
  Validation: Cannot delete if chargers using that version

POST /api/admin/firmware/chargers/{id}/update - Trigger OCPP update (single)
  Request: { "firmware_file_id": 1 }
  Validation: Charger online, no active transaction
  Response: FirmwareUpdate record (PENDING status)

POST /api/admin/firmware/bulk-update - Trigger updates for multiple chargers
  Request: { "firmware_file_id": 1, "charger_ids": [1,2,3] }
  Response: { "success": [...], "failed": [...] }

GET /api/admin/firmware/chargers/{id}/history - Get update history
  Response: Paginated list of FirmwareUpdate records

GET /api/admin/firmware/updates/status - Real-time dashboard
  Response: { "in_progress": [...], "summary": { pending, downloading, installing, completed_today, failed_today } }

# Public Endpoints (NO authentication)
GET /api/public/stations/map - Charger map data with real-time availability (rate limited: 20 req/60s per IP)
  Response: { "data": [{ id, name, latitude, longitude, address, available_chargers, total_chargers, connector_types, connector_details, price_per_kwh, min_price_per_kwh_incl_tax, max_price_per_kwh_incl_tax, franchisee_name }], "total" }
  Note: `price_per_kwh` is the min tax-EXCLUSIVE rate across the station's chargers (kept for compat). All user-facing UI renders the incl-tax range — when min==max the UI shows a single value, otherwise "₹min–₹max/kWh (incl. GST)". Map endpoint deliberately omits per-charger detail for privacy.

GET /api/public/stations - Authenticated station list (full per-charger detail)
  Response data items include `chargers[]: { charge_point_string_id, name, latest_status, connectors, tariff_per_kwh, tariff_per_kwh_incl_tax, tariff_gst_percent }` plus the station-level `min/max_price_per_kwh_incl_tax`. The /stations detail modal renders per-charger tariff rows from this; the list card uses the station range.

GET /api/firmware/latest - Get latest firmware for non-OCPP charge points
  Response: { "version", "filename", "download_url", "checksum", "file_size" }
  Response: 404 if no active firmware
```

**Firmware Static Files**:
- `/firmware/{filename}` - Direct firmware download URL (static file serving)

**Firmware Flow**:
1. OCPP: Admin triggers → UpdateFirmware command → FirmwareStatusNotification tracking → charger.firmware_version updated
2. Non-OCPP: Device polls `/api/firmware/latest` → downloads from URL → verifies checksum → installs

**Documentation**: See `/backend/docs/FIRMWARE_API.md` for ESP32/Arduino integration examples

### **NEW**: QR Code Management APIs (`/api/admin/qr-codes/*`)
```
POST /api/admin/qr-codes - Create Razorpay UPI QR code for charger
  Request: { "charger_id": 10 }
  Response: { id, charger_id, razorpay_qr_code_id, image_url, short_url, is_active }

GET /api/admin/qr-codes - List QR codes with pagination
  Params: { page?, limit?, status? (active/inactive), search? }
  Response: { data: [...], total, page, limit }

GET /api/admin/qr-codes/{qr_id} - QR code detail with payment stats
  Response: { ...qr_code, payment_count, total_revenue, total_refunds }

POST /api/admin/qr-codes/{qr_id}/close - Deactivate QR code
  Response: { "message": "QR code closed", "id": qr_id }

GET /api/admin/qr-codes/{qr_id}/payments - Payment history for QR code
  Params: { page?, limit?, status? }
  Response: { data: [...QRPayment], total, page, limit }

GET /api/admin/qr-codes/charger/{charger_id} - QR code for specific charger
  Response: ChargerQRCode | null
```

### Webhook APIs (`/webhooks/`)
```
POST /webhooks/clerk - Clerk user lifecycle events (signature verified)
POST /webhooks/razorpay - Razorpay payment events (HMAC-SHA256 signature verified)
  Events: payment.captured, payment.failed, order.paid, qr_code.credited
  QR Flow: qr_code.credited → QRPaymentService.handle_qr_payment() → user resolution → RemoteStart → budget enforcement → billing → refund
```

**Cross-Environment Webhook Handling**: Production and staging share the same Razorpay live keys. Both environments receive all webhook events. Handlers gracefully skip "not found" transactions (return 200, log warning) instead of raising errors — this prevents Razorpay retries for events that belong to the other environment. Only DB/API errors return 500.

### Legacy APIs (Backward Compatibility)
```
GET /api/charge-points - Connected charger list
POST /api/charge-points/{id}/request - Send OCPP command  
GET /api/logs - OCPP message logs
GET /api/logs/{charge_point_id} - Logs for specific charger
```

---

## Current State & Recent Updates

### voltNOW rebrand (2026-05-15)
- Navbar: `frontend/components/Navbar.tsx` renders the voltNOW logo image instead of the "OCPP Admin/User" text. Two assets are shipped under `frontend/public/`: `voltnow-logo.png` (black, for light theme) and `voltnow-logo-light.png` (grey, for dark theme); swapped at runtime via Tailwind's `dark:` modifier (`block dark:hidden` / `hidden dark:block`). The right-side role chip stays as the source of truth for ADMIN/USER/FRANCHISEE.
- Page title: `frontend/app/layout.tsx` metadata.title is "voltNOW EV Charging".
- Invoice PDF (`backend/services/invoice_service.py:generate_pdf`): every page is stamped with the voltNOW A4 header/footer image (`backend/assets/invoice_header_footer.png`) via an `onFirstPage`/`onLaterPages` callback. `SimpleDocTemplate` top/bottom margins are 38 mm / 22 mm so content clears the lime "EV Charging" header band and the lime footer band. The previously green "TAX INVOICE" title is now a small black caption above the meta row. Missing asset is non-fatal — falls back to legacy 15 mm margins and logs a warning.
- "OCPP" still appears in product copy where it names the protocol (e.g. "OCPP StatusNotification", "OCPP UpdateFirmware", "OCPP 1.6") — those mentions are intentionally kept.

### Latest Changes (March 2025 - Branch: 57-qr-based-appless-transaction)

**Major New Feature: QR-Based Appless Charging**
- Customers scan a Razorpay UPI QR code at the charger, pay any amount via UPI, and start charging without an app or account
- Full lifecycle: webhook → user resolution → RemoteStart → budget enforcement → billing → refund
- Admin QR management pages with payment history and revenue tracking
- Idempotent webhook processing, stale payment detection, double-payment guard
- Redis-cached budget enforcement during MeterValues with auto-stop
- Automated partial refund of unused balance via Razorpay
- UPI_GUEST user creation for new customers
- 3 new database migrations, ~600 lines of service code

**Docker Compose Production Deployment**
- Complete containerized deployment: backend + frontend + nginx + redis + postgres
- Multi-stage Docker builds, nginx SSL/WebSocket proxy, Makefile targets
- Separate configs for dev/staging/prod environments

**Monitoring & Observability**
- Sentry error tracking with ASGI middleware
- New Relic APM with `@trace_transaction` decorator for OCPP messages
- Structured logging with timestamps and correlation IDs
- `core/connection_manager.py` - Refactored charger connection management

**Recent Commits** (Branch: 57-qr-based-appless-transaction):
- e925ef0: "removed verification" - Removed verification step
- 24788e7: "fetch by upi id fix" - UPI ID fetch fix
- 91c6241: "resume, 3.5kw, upiid" - Resume support, 3.5kW, UPI ID handling
- ffe72e0: "billing retry" - Enhanced billing retry service (QR refunds, orphaned payments, stale suspended)
- dd980fb: "remote start double prevention" - Check if transaction already started before retry
- 514f0d3: "revert preparing" - Revert preparing transaction state
- f72791e: "sanitze" - StopTransaction reason sanitization via route_message override
- 0b9ca78: "handling failed transactions" - Transaction failure detection + QR refund on StatusNotification
- c6f2a20: "logging structure" - Improved logging format
- a72f5e7: "retry" - RemoteStart retry logic
- 0327fb4: "idempotency" - Webhook idempotency checks
- b32dbef: "webhook issue fix" - Webhook processing fixes
- f6920c1: "multi qr" - Allow multiple QR codes per charger
- 5176ce2: "tarrif" - Tariff-based budget calculation
- f47660c: "appless qr" - Core QR payment implementation

### Previous Features (still active)
- PostBootState Push - Server pushes meter values after every reboot via DataTransfer
- Transaction Suspend/Resume - Survives charger reboots with auto-stop timeout
- **Disconnect Handler** - Detects charger disconnections, suspends transactions, auto-stops after 180s timeout with billing
- StopTransaction Reason Sanitization - route_message override for non-standard values
- Enhanced Billing Retry - QR refund retries, orphaned payment cleanup, stale suspended cleanup
- Remote Start Double Prevention - Checks if transaction already started before retry
- Native Mobile App (Capacitor) - iOS/Android with QR scanning, geolocation, payments
- Firmware OTA Update System - Admin upload, OCPP UpdateFirmware, real-time dashboard
- Razorpay Payment Integration - Wallet recharge with dual verification
- Data Retention Service - 90-day cleanup for signal quality and OCPP logs
- Signal Quality Monitoring - RSSI/BER via OCPP DataTransfer
- Charger Error Tracking - OCPP StatusNotification error capture with resolution
- Zero Charged Transaction Handling, User Transaction Pages, My Sessions, Running Balance

### Technology Stack
**Authentication**: Clerk 6.29.0 (web) / 5.56.1 (mobile) for JWT and role management + UPI_GUEST for appless users
**Payment Gateway**: Razorpay SDK 2.0.0 (backend) + Razorpay Checkout.js (web) + capacitor-razorpay 1.3.0 (mobile) + UPI QR code generation + refunds
**Database**: Tortoise ORM 0.25.1 (async) with PostgreSQL and SSL in production
**Web Frontend**: Next.js 15.3.8 with App Router, TypeScript 5.x, React 19, TanStack Query 5.81.2, Shadcn/ui
**Mobile App**: Capacitor 7.4.4 + React 19 + Vite 7.2.4 + TypeScript 5.9 + TanStack Query 5.90.10
**Backend**: FastAPI 0.115.12 with Uvicorn 0.34.3, Python-OCPP 2.0.0
**Real-time**: Redis for connection state + QR session budget caching, TanStack Query polling for frontend/app updates
**Deployment**: Docker Compose on AWS EC2 (backend, frontend, nginx, redis, postgres)
**Monitoring**: Sentry (error tracking) + New Relic (APM) + structured logging with correlation IDs
**Maps**: React Leaflet 5.0.0 (both web and mobile) + Leaflet 1.9.4
**Charts**: Recharts 3.2.1 for energy visualization
**Testing**: Pytest 8.3.4 with async support
**Mobile Build**: Vite for development and production builds of Capacitor app

### Current Production Deployment
- **Infrastructure**: AWS EC2 with Docker Compose (app.voltlync.com)
- **Backend**: FastAPI in Docker container with auto-migrations on startup
- **Web Frontend**: Next.js in Docker container with standalone output
- **Reverse Proxy**: Nginx with SSL termination, WebSocket proxy for `/ocpp/`
- **Database**: PostgreSQL in Docker with persistent volume
- **Cache**: Redis in Docker (`--maxmemory 256mb --maxmemory-policy allkeys-lru`)
- **Mobile App**: Ready for App Store submission (iOS App Store + Google Play Store)
  - App configured with bundle ID: com.lyncpower.user
- **Monitoring**: Sentry + New Relic + health check endpoints

### Staging Deployment
- **Infrastructure**: AWS EC2 t3.medium (staging.voltlync.com), cloned from production AMI
- **Branch**: `develop` (pushed via `make staging-push`, deployed via `make staging-deploy`)
- **Compose**: `docker-compose.staging.yml` + `.env.staging`
- **Shared keys**: Same Clerk app and Razorpay live keys as production (QR payments don't work in test mode)
- **Makefile targets**: `staging-*` mirrors `prod-*` (staging-push, staging-deploy, staging-logs, staging-migrate, etc.)

### Known Working Features
✅ Complete OCPP 1.6 message handling with all core messages
✅ Real-time charger status monitoring with Redis-backed connection tracking
✅ Transaction lifecycle management with automated billing and retry logic
✅ **Transaction Suspend/Resume** - Transactions survive charger reboots via SUSPENDED state
  - BootNotification suspends (not fails) ongoing transactions
  - Background timeout auto-stops after 300s with billing + QR refund
  - DataTransfer GetLastMeterValue for seamless resume from last meter reading
  - Resume tracking: suspended_at, resumed_at, resume_count fields
✅ **PostBootState Push** - Server pushes meter values and pending transaction state after every BootNotification
  - `@after('BootNotification')` hook in main.py
  - vendorId=VOLTLYNC, messageId=PostBootState
  - Always sends lastMeterValueWh (charger has no internal meter)
  - If suspended transaction exists: includes transactionId, startMeterValueWh, energyConsumedWh
  - Firmware spec: `docs/firmware/post-boot-state-spec.md`
✅ **NEW**: Disconnect-Aware Transaction Handling
  - Detects charger disconnections (power failures, network issues) via `disconnect_handler.py`
  - On disconnect: suspends active transactions (status -> SUSPENDED), starts configurable timeout (default 180s)
  - If charger reconnects within timeout: transaction can be resumed via PostBootState DataTransfer
  - If timeout expires without reconnect: transaction auto-stopped (DISCONNECT_TIMEOUT), energy calculated, billing applied
  - BootNotification from reconnecting charger resets the suspend timeout
  - Startup sweep (`sweep_stale_suspended_transactions()`) catches orphaned SUSPENDED transactions after server restart
  - Disconnect callback registered via `connection_manager.register_on_disconnect()`
  - **Resume staleness guard** (defense-in-depth): every resume entry point — MeterValues auto-resume, BootNotification per-txn handler (`_handle_ongoing_transaction_on_boot`), and GetLastMeterValue DataTransfer — calls `transaction_finalizer.is_resume_too_stale()` before allowing the resume. If the gap between the txn's last activity (suspended_at, latest MeterValue, or start_time) and now exceeds `MAX_RESUME_GAP_SECONDS=900`, the txn is finalized with stop_reason `STALE_RECONNECT` instead. This catches the case where the disconnect handler silently failed (swallowed exception, process restart killing the in-memory timer) and a charger reconnects an hour later — without this guard the BootNotification edge-case branch would suspend the still-RUNNING txn, MeterValues would auto-resume it, and the user would be billed for whatever the meter reported on the post-disconnect side. Audit action `transaction.resume_blocked` records each guard hit with `gap_seconds` and `trigger`.
✅ **QR-Based Appless Charging** - Scan UPI QR, pay, charge without app/account
  - Razorpay UPI QR code generation and management
  - Webhook-driven payment processing with idempotency
  - User resolution: phone → VPA → UPI_GUEST → system guest
  - Budget enforcement during MeterValues with auto-stop
  - Automated partial refund of unused balance
  - Admin QR management pages with payment history
✅ **Native Mobile App (100% Complete)** - iOS/Android Capacitor app
  - QR code scanning for charger access
  - Interactive station finder with geolocation and distance calculation
  - Live charging session monitoring with real-time meter values
  - Remote start/stop charging from mobile
  - Combined transaction history (charging + wallet)
  - Native Razorpay payment integration
  - Pull-to-refresh, network status detection, error boundaries
  - Ready for App Store submission
✅ **NEW**: Razorpay payment integration for wallet recharge
  - Secure order creation and payment verification
  - Webhook integration for reliability
  - Idempotent processing to prevent double-crediting
  - Complete payment history tracking
✅ **NEW**: Zero energy transaction handling (no billing for 0 kWh)
✅ **NEW**: User transaction history pages with pagination and filtering
✅ **NEW**: Wallet transaction history with running balance calculation
✅ **NEW**: My Sessions page for unified user transaction view with recharge capability
✅ **Firmware OTA Update System** (complete implementation)
  - Admin firmware file upload with version management
  - OCPP UpdateFirmware command integration
  - FirmwareStatusNotification progress tracking
  - Real-time update dashboard with auto-refresh (10s polling)
  - Safety validations (online check, no active transactions)
  - Bulk update capability for multiple chargers
  - **Public API for non-OCPP devices** (`GET /api/firmware/latest`)
  - MD5 checksum verification for integrity
  - Comprehensive update history tracking
✅ **Remote Charger Reset** (OCPP 1.6 compliant)
  - Hard reset: Complete reboot with safety validation (blocked during charging)
  - Soft reset: Graceful restart without interruption
  - Admin UI with reset type selection dialog
  - Visual warnings for unsafe operations
  - Automatic BootNotification after reset
  - Full OCPP compliance and audit logging
✅ **Signal Quality Monitoring** (via OCPP DataTransfer)
  - Real-time cellular signal quality tracking (RSSI, BER)
  - Vendor-specific DataTransfer handler (JET_EV1 chargers)
  - Historical signal quality data with time-based filtering
  - Color-coded signal strength display (Good/Fair/Poor/Unknown)
  - Auto-refresh every 5 seconds on charger detail page
✅ **Data Retention Service** (Automated Cleanup)
  - Background service for database maintenance
  - Signal quality data cleanup (90-day retention)
  - OCPP log cleanup (90-day retention)
  - Runs every 24 hours with configurable intervals
  - Error handling and graceful shutdown
✅ **NEW**: Charger Error Tracking System
  - OCPP StatusNotification error capture with vendor codes
  - Error history API with pagination and filtering
  - Resolution tracking (auto-resolves on NoError)
  - Frontend error history display with color-coded badges
  - Clear visual distinction between error code and vendor code
✅ Remote start/stop charging with immediate OCPP command execution
✅ Availability control for chargers (Operative/Inoperative)
✅ Role-based admin dashboard with comprehensive management tools
✅ User-friendly interfaces with interactive maps (React Leaflet 5.0.0) and QR scanning (ZXing 0.21.3)
✅ Wallet system with automatic billing on transaction completion
✅ Connection state tracking with automatic cleanup of dead connections
✅ Comprehensive logging system for OCPP compliance and debugging
✅ Energy chart visualization with CSV export (Recharts 3.2.1)  

---

## Code Patterns & Conventions

### Backend Patterns
```python
# OCPP message handlers use @on decorator
@on('StartTransaction')
async def on_start_transaction(self, connector_id, id_tag, meter_start, **kwargs):
    # Business logic with user validation and vehicle profile creation
    return call_result.StartTransaction(transaction_id=id, id_tag_info={"status": "Accepted"})

# Database operations are async with relationships
charger = await Charger.filter(charge_point_string_id=cp_id).prefetch_related('station').first()
await charger.save()

# Redis connection state management  
await redis_manager.add_connected_charger(charger_id, connection_data)
is_connected = await redis_manager.is_charger_connected(charger_id)
```

### Frontend Patterns
```typescript
// TanStack Query for data fetching with role-based optimization
const { data: chargers } = useChargers({ refetchInterval: 10000 }); // Admin real-time
const { data: stations } = useStations({ staleTime: 2 * 60 * 1000 }); // User longer cache

// NEW: User transaction queries with pagination
const { data: transactions } = useUserTransactions(userId, { page: 1, limit: 10 });
const { data: walletTxns } = useUserWalletTransactions(userId, { page: 1, limit: 15 });

// Role-based component rendering
const Dashboard = () => {
  const { user } = useUser();
  const isAdmin = user?.publicMetadata?.role === 'ADMIN';

  return isAdmin ? <AdminDashboard /> : <UserDashboard />;
};

// Optimistic updates with rollback
const mutation = useMutation({
  onMutate: (variables) => {
    queryClient.setQueryData(['chargers'], optimisticUpdate);
  },
  onError: (error, variables, context) => {
    queryClient.setQueryData(['chargers'], context.previousData);
  }
});
```

---

## Development Environment Setup

### Backend Setup
```bash
cd backend
# IMPORTANT: Always activate the virtual environment first
source .venv/bin/activate
pip install -r requirements.txt
# Set environment variables: DATABASE_URL, REDIS_URL, CLERK_*, CORS_ORIGINS
# Required Clerk vars for JWT verification: CLERK_SECRET_KEY, CLERK_JWKS_URL, CLERK_ISSUER
# Prod: CLERK_JWKS_URL=https://clerk.voltlync.com/.well-known/jwks.json
# Staging: use your Clerk dev-tenant JWKS URL
# CORS: set CORS_ORIGINS=https://app.voltlync.com (prod) / https://staging.voltlync.com (staging)
python main.py  # Starts on port 8000 with OCPP WebSocket endpoint
```

**Note for AI Assistants**: Always activate the virtual environment with `source .venv/bin/activate` before running any Python commands in the backend directory. The project uses a virtual environment located at `backend/.venv/`.

### Frontend Setup  
```bash
cd frontend
npm install
# Set NEXT_PUBLIC_API_URL=http://localhost:8000
# Set NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY and CLERK_SECRET_KEY
npm run dev  # Starts on port 3000 with role-based routing
```

### Database Migrations
```bash
cd backend
source .venv/bin/activate
aerich migrate --name "description"  # Generate migration
aerich upgrade  # Apply migration to database
```

### Seeding the Dev DB
Seed scripts live in `backend/scripts/` and run inside the backend container
(no local venv needed — matches `feedback_docker_exec`). All scripts are
idempotent.

```bash
# One-shot orchestrator — runs every seeder in order on a shared connection
make seed CLERK_ADMIN_ID=user_xxx ADMIN_EMAIL=you@example.com
# Equivalent direct invocation:
docker exec -e CLERK_ADMIN_ID=user_xxx -e ADMIN_EMAIL=you@example.com \
    ocpp-backend python scripts/seed_all.py
```

Env vars:
- `CLERK_ADMIN_ID` — your Clerk user id; seeded as the ADMIN user.
- `ADMIN_EMAIL` — required because `app_user.email` is NOT NULL UNIQUE. Default `admin@voltlync.dev`.
- `CLERK_USER_ID` / `USER_EMAIL` — optional, for a second regular user.

Scripts:
- `seed_docker.py` — core: users + wallets, 5 Bangalore stations, 10 chargers, global tariff (₹12/kWh, 18% GST), 5 completed transactions with billing fields filled.
- `seed_franchisees.py` — 3 franchisees (`ACTIVE` "Bangalore EV Partners", `KYC_UNDER_REVIEW` "Pending KYC LLP", `SUSPENDED` "Suspended Owner"), 1 stakeholder, links MG Road + Koramangala stations to the ACTIVE franchisee.
- `seed_all.py` — orchestrator. Opens one Tortoise connection and runs each seeder; individual seeders no-op their own init/close when `Tortoise._inited`.

Adding a new seeder: implement a `Seeder` class with `init_db`/`close_db`/`seed_all`, follow the `_owns_connection` pattern in `seed_docker.py`, then append the class to `SEEDERS` in `seed_all.py`. Idempotency convention: `get_or_create` keyed on the natural unique field (`clerk_user_id`, `name`, `charge_point_string_id`, `contact_email`, etc).

Out of scope (deferred): QR payments, commission ledger entries (when built, call `FranchiseeSettlementService.process_settlement()` rather than raw inserts), firmware files. Operational/event tables (AuditLog, OCPPLog, WebhookEvent, etc.) are populated by runtime traffic, not by seed scripts.

---

## Testing Framework

### Test Categories  
```bash
pytest -m unit          # Fast tests (~1 second) - models, API endpoints
pytest -m integration   # Full OCPP WebSocket tests (~45 seconds) - complete charging sessions
pytest -m infrastructure # Database/Redis tests (~5 seconds) - external dependencies
```

### OCPP Simulators
- **`simulators/ocpp_simulator_full_success.py`** - Complete charging session simulation
- **`simulators/ocpp_simulator_change_availability.py`** - Availability command testing
- **`simulators/ocpp_simulator_vendor_errors.py`** - Vendor error code testing
  - Tests standard OCPP error codes and vendor-specific codes
  - Interactive mode for custom error injection
  - Complete error lifecycle testing (error → resolution)
- **`simulators/ocpp_simulator_disconnect.py`** - **NEW** Disconnect scenario testing
  - Synchronous websocket-based simulator for testing charger disconnect handling
  - 3 test modes via CLI flags:
    - `--test-no-reconnect`: Disconnects mid-charge, never reconnects. Tests auto-stop after timeout.
    - `--test-reconnect`: Disconnects mid-charge, reconnects after configurable delay (`--reconnect-delay`). Tests suspend/resume flow.
    - `--test-no-transaction`: Disconnects with no active transaction. Tests clean disconnect handling.
  - Waits for RemoteStartTransaction from server before starting transactions (matches real charger behavior)
  - On reconnect: parses PostBootState DataTransfer to detect pending transactions, resumes charging if `hasPendingTransaction: true`

### Test Environment
- **Configuration**: `backend/pyproject.toml` with async support and markers
- **Fixtures**: `backend/tests/conftest.py` with database setup and cleanup
- **Coverage**: Available with `pytest --cov=. --cov-report=html`

---

## Technical Debt & Known Issues

### ~~Critical Issue: Boot Notification Transaction Handling~~ — RESOLVED
**Resolution**: Implemented Transaction Suspend/Resume (Migration #8, March 2026)
- Ongoing transactions now marked SUSPENDED (not FAILED) on charger reboot
- Background timeout auto-stops after `SUSPEND_TIMEOUT_SECONDS` (300s default) with wallet billing + QR refund
- DataTransfer `GetLastMeterValue` enables seamless resume from last meter reading
- Resume fields: `suspended_at`, `resumed_at`, `resume_count`

### Known Gaps & Missing Features
❌ **Push Notifications (NOT Implemented)**
- **Original Proposal**: Firebase Cloud Messaging for session notifications
- **Status**: NOT implemented in mobile app
- **Impact**: Users must manually check app for charging completion
- **Dependencies**: Firebase SDK, FCM setup, notification permissions
- **Estimated Effort**: 8-12 hours (FCM setup + backend integration + mobile implementation)

❌ **Offline Mode**
- **Status**: Marked as future enhancement in IMPLEMENTATION_STATUS.md
- **Impact**: App requires network connectivity for all operations
- **Suggested**: Local caching of station data and session history

❌ **Biometric Authentication**
- **Status**: Marked as future enhancement
- **Impact**: Users must manually sign in each time
- **Suggested**: Face ID / Touch ID for quick access

### Recently Fixed Issues
✅ **Boot Notification Transaction Loss** - Resolved with suspend/resume mechanism (March 2026)
✅ **StopTransaction Validation Rejection** - Fixed with `route_message()` reason sanitization
✅ **Remote Start Duplicates** - Fixed with double-prevention check (charger already CHARGING)
✅ **Failed QR Refunds** - Fixed with billing retry service processing REFUND_FAILED payments
✅ **Zero Energy Billing** - Fixed in commit e3f6b38 (now handles 0 kWh gracefully)
✅ **Decimal Precision** - Fixed in commit 38816d3 (shows 0.01 kWh accuracy)
✅ **Chart Scaling** - Fixed in commit 38816d3 (improved readability)
✅ **Ghost Sessions** - Fixed in commits b385b61, 9fe8f2f (improved cleanup)

### Performance Optimization Opportunities
1. **N+1 Queries**: Some charger list operations could use bulk Redis operations
2. **Frontend Bundle**: ~2MB bundle could be reduced 30-40% with admin-only code splitting
3. **Database Queries**: Could benefit from additional indexing for OCPP operations

### Security Enhancements Needed
1. **OCPP Message Validation**: Limited schema validation for incoming OCPP messages
2. **Rate Limiting**: No rate limiting implemented for API endpoints
3. **Audit Logging**: Could enhance security event logging beyond OCPP messages

---

## Common Development Tasks

### Adding a New OCPP Message Handler
1. Add handler method with `@on('MessageName')` decorator in `main.py`
2. Update database schema if needed (create migration with `aerich migrate`)
3. Add frontend API integration if user-facing (update `api-services.ts`)
4. Write integration tests in `tests/test_integration.py`

### Adding a New API Endpoint
1. Add route to appropriate router (`routers/stations.py`, `routers/chargers.py`, etc.)
2. Add CRUD functions if database operations needed
3. Add frontend service function in `lib/api-services.ts`  
4. Create TanStack Query hook in `lib/queries/`
5. Update TypeScript types in `types/api.ts`

### Debugging OCPP Issues
1. Check `log` table for all OCPP messages with correlation IDs
2. Verify charger exists in database with correct `charge_point_string_id`  
3. Check Redis connection state: `await redis_manager.is_charger_connected(cp_id)`
4. Monitor heartbeat: check `last_heart_beat_time` in charger table
5. Use OCPP simulators for controlled testing

### Role-Based Feature Development
1. **Backend**: Use `RequireAdmin` or `RequireAuth` dependencies in route handlers
2. **Frontend**: Wrap components in `<AdminOnly>`, `<UserOnly>`, or `<AuthenticatedOnly>`
3. **API Services**: Ensure proper error handling for 403 Forbidden responses
4. **Testing**: Test both admin and user access patterns

---

## Important Constraints & Considerations

### OCPP Compliance
- Must maintain OCPP 1.6 message format exactly
- All timestamps in ISO 8601 format with 'Z' suffix  
- Energy values: Convert Wh to kWh (divide by 1000) for database storage
- Status values must match OCPP 1.6 enum exactly
- Complete audit trail required for certification

### Performance Considerations
- Redis used for connection state (fast O(1) lookups)
- Database connections pooled (max 20 connections)
- Frontend polling every 10 seconds (optimized by role and data type)
- Bulk operations for admin dashboard efficiency  
- TanStack Query caching optimized by data volatility

### Data Integrity & Business Logic
- `charge_point_string_id` must be unique across chargers
- Transactions linked to users via RFID card ID lookup
- OCPP message logging essential for compliance/debugging
- Automatic billing on transaction completion with retry mechanism
- Connection cleanup prevents resource leaks

---

## Security & Production Notes

### Current Security
- CORS configured for specific origins (development and production)
- Database credentials via environment variables
- Clerk-based JWT authentication with role validation
- OCPP WebSocket validates charger registration before connection
- SSL required for production database connections

### Production Configuration
- PostgreSQL with SSL required connections
- Redis connection URL from environment variables
- Clerk webhook signature validation for user lifecycle events
- Frontend API URL configurable via environment
- Structured logging with correlation IDs for audit trail

---

## Key Files for LLM Understanding

**If you need to understand the codebase, start with these files in order**:

1. **`backend/main.py`** - Core OCPP WebSocket handling, all message handlers, FastAPI app setup
2. **`backend/models.py`** - Complete database schema with relationships and OCPP-compliant enums
3. **`app/src/App.tsx`** - **NEW** Mobile app entry point with Clerk + QueryClient setup
4. **`app/src/routes.tsx`** - **NEW** Mobile app routing with all screens
5. **`frontend/app/page.tsx`** - Web role-based dashboard to understand user experience patterns
6. **`backend/routers/chargers.py`** - Most complex API with OCPP integration and admin operations
7. **`frontend/components/RoleWrapper.tsx`** - RBAC implementation patterns
8. **`backend/auth_middleware.py`** - Clerk authentication and role validation
9. **`frontend/lib/api-client.ts`** - Frontend-backend integration with automatic JWT handling
10. **`app/capacitor.config.ts`** - **NEW** Capacitor configuration for native builds

**For specific functionality**:
- **OCPP message handling** → `main.py` (ChargePoint class with @on decorators)
- **Database schema & relationships** → `models.py`
- **Admin APIs & OCPP commands** → `routers/` directory
- **Web user interfaces & role-based UI** → `frontend/app/` directory
- **Mobile app screens** → **NEW** `app/src/screens/` directory (6 screens)
- **Native mobile features** → **NEW** `app/src/hooks/` + Capacitor plugins
- **Real-time features & caching** → `redis_manager.py` + `lib/queries/` hooks (both web and mobile)
- **Authentication & RBAC** → `auth_middleware.py` + `middleware.ts` (web) + `App.tsx` (mobile)
- **QR-based appless charging** → `services/qr_payment_service.py` + `routers/qr_codes.py` + `routers/webhooks.py` (qr_code.credited handler)
- **Financial operations** → `services/wallet_service.py` + `services/billing_retry_service.py` + `services/razorpay_service.py` + `services/qr_payment_service.py`
- **Firmware OTA updates** → `routers/firmware.py` + `services/storage_service.py` + `frontend/app/admin/firmware/page.tsx` + `lib/queries/firmware.ts`
- **Data retention & cleanup** → `services/data_retention_service.py`
- **Transaction suspend/resume** → `main.py` (BootNotification handler + `_suspend_timeout`) + `main.py` (DataTransfer GetLastMeterValue)
- **Connection management** → `core/connection_manager.py` (tombstone, heartbeat, ghost session detection, OCPP command dispatch)
- **Billing retry & cleanup** → `services/billing_retry_service.py` (failed billing, QR refunds, orphaned payments, stale suspended)

**For troubleshooting**:
- **OCPP communication issues** → Check `log` table and `redis_manager.py` connection state
- **Authentication problems** → Check Clerk webhook processing in `routers/webhooks.py`
- **Transaction billing issues** → Check `wallet_service.py` and BILLING_FAILED status handling
- **Web frontend role issues** → Check `middleware.ts` and role-based component wrappers
- **Mobile app issues** → **NEW** Check Capacitor logs, native permissions, network status component
- **Native feature issues** → **NEW** Check Capacitor plugin installation and platform-specific configs
- **Payment issues** → Check Razorpay service logs, webhook signatures, `wallet_payments.py` router
- **QR payment issues** → Check `services/qr_payment_service.py` logs, Redis `qr_session:*` keys, `QRPayment` table status, Razorpay webhook delivery
- **Transaction resume issues** → Check `suspended_at`/`resumed_at` fields, `SUSPEND_TIMEOUT_SECONDS` env var, BootNotification logs
- **Stale transaction cleanup** → Check billing retry service logs, SUSPENDED transactions >5h old
- **Docker/deployment issues** → Check `docker-compose.prod.yml`, `nginx/prod.conf`, `backend/docker-entrypoint.sh`, `Makefile`

### Docker & Deployment Quick Reference
```bash
# Key Makefile targets
make prod-up          # Start production stack
make prod-down        # Stop production stack
make prod-migrate     # Run database migrations
make prod-logs        # Tail all container logs
make docker-build     # Build all images

# Test QR webhook locally
docker compose exec backend python scripts/test_qr_webhook.py --charger-id 10 --amount 500
```

This context should give any LLM a solid foundation for understanding and working with this modern, production-ready OCPP 1.6 CSMS with role-based access control, QR-based appless charging, comprehensive user experience features, Docker deployment, and native mobile applications for iOS and Android.