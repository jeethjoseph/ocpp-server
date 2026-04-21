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
**Deployment**: AWS EC2 with Docker Compose (backend, frontend, nginx, redis, postgres)
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
- **`public_stations.py`** - Public unauthenticated station/charger discovery (`/api/public/stations/*`) for user-facing pages
- **`public_qr_transactions.py`** - Public QR transaction history lookup by UPI VPA (`/api/public/qr-transactions`) — no auth, paginated, minimal data exposure
- **`qr_codes.py`** - Admin QR code CRUD for appless charging (`/api/admin/qr-codes/*`)
  - Create/list/close/regenerate QR codes linked to chargers
  - Payment history and revenue stats per QR code
  - All QRs are platform-owned: payments land in VoltLync's nodal balance, never scoped to a franchisee's linked account. The franchisee's share is disbursed via a Route transfer *after* the session settles (see `franchisee_settlement_service`). Legacy rows with `ChargerQRCode.owner_razorpay_account_id IS NOT NULL` must be regenerated via the close-and-recreate endpoint before new payments flow correctly.
- **`franchisee_portal.py`** - Franchisee-facing portal API (`/api/franchisee/*`)
  - Dashboard, stations, chargers, transactions, settlements, profile, QR codes
  - `/qr-codes` endpoints support full CRUD on the franchisee's own chargers' QRs (list with `can_create_direct` / `payee_display_name`, create, regenerate, close). Regenerate is the retroactive compliance path: once Razorpay KYC completes, the franchisee clicks it to upgrade each platform-owned QR into a franchisee-owned one. All mutations audit-log with `actor_type=franchisee`.
- **`webhooks.py`** - Clerk webhook processing for user lifecycle (`/webhooks/clerk`) + Razorpay webhook handler (`/webhooks/razorpay`)
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
  - `process_qr_session_billing()` - Called from StopTransaction, calculates cost with GST, issues refund. Formula: `energy_charge = energy_kwh * rate`, `gst = energy_charge * gst_percent / 100`, `refund = amount_paid - energy_charge - gst - platform_fee`
  - `_resolve_platform_fee()` - Resolves actual Razorpay fee: webhook payload → API fetch → 2% estimate fallback
  - Fee fields on QRPayment: `platform_fee` (total fee), `razorpay_commission` (fee - tax), `razorpay_gst` (tax), `fee_source` ('webhook'|'api'|'estimated')
  - Config: `RAZORPAY_PLATFORM_FEE_PERCENT=2.0` (fallback only), `MINIMUM_REFUND_AMOUNT=1.0`, `QR_PAYMENT_PENDING_TIMEOUT=300`
- **`wallet_service.py`** - Billing calculations and automated payment processing
  - Zero energy transaction handling (no billing for 0 kWh)
  - Wallet top-up processing with idempotency (`process_wallet_topup()`)
  - Atomic transaction processing with SELECT FOR UPDATE
  - Tariff-based billing calculation with GST: `energy_charge = energy_kwh * rate_per_kwh`, `gst = energy_charge * gst_percent / 100`, `total = energy_charge + gst` (default 18% GST, configurable per tariff via `gst_percent` field)
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
  - `check_zero_energy()` - Called from MeterValues handler. Tracks energy progress in Redis, schedules `RemoteStopTransaction` if energy hasn't advanced for `ZERO_ENERGY_TIMEOUT_SECONDS` (120s) after `ZERO_ENERGY_GRACE_PERIOD_SECONDS` (60s) grace
  - **W5 hook**: when energy advances, pops `disconnect_handler._disconnect_reset_count` for the transaction, allowing long sessions with intermittent disconnects to never trip the flap detector
  - `clear_zero_energy_tracking()` - Cleanup hook called from `transaction_finalizer.finalize_stopped_transaction`
  - Config: `ZERO_ENERGY_TIMEOUT_SECONDS=120`, `ZERO_ENERGY_GRACE_PERIOD_SECONDS=60`
- **`billing_retry_service.py`** - Background service (30-min interval) for failed transaction recovery, QR refund retries, orphaned QR payment cleanup, stale suspended transaction cleanup
- **`firmware_update_service.py`** - Background service that processes pending firmware updates on startup
- **`razorpay_service.py`** - Razorpay payment gateway integration
  - Order creation and payment verification
  - Webhook signature verification (HMAC SHA256)
  - **QR code creation**: `create_qr_code(payee_name, description, account_id=None)`, `close_qr_code(id, account_id=None)`, `fetch_qr_code(id, account_id=None)`. `account_id` is still accepted for backward-compatible close/fetch on legacy franchisee-scoped QRs but NEW QRs are always created with `account_id=None` (platform-owned); the franchisee's share is transferred post-settlement via Route.
  - **Helpers**: `build_qr_payee_name(business_name, charger_name)` composes the `name` metadata (50-char cap; falls back to "VoltLync" when no franchisee). `build_qr_description(...)` composes the rendered descriptor line.
  - **Refunds**: `refund_payment(payment_id, amount, notes, idempotency_key)` — `idempotency_key` is sent as `X-Refund-Idempotency` so retries dedupe server-side. Callers use `f"qr_payment_{id}"` as the stable key.
  - **Route transfers**: `create_transfer(account_id, amount_paise, notes, idempotency_key)` — `idempotency_key` is sent as `X-Transfer-Idempotency`. Retries with the same key are deduped by Razorpay (replays original response); same key + different body → 400.
  - **Linked accounts**: `create_linked_account(payload)` — caller builds the payload including `reference_id=f"franchisee_{id}"`, `business_type`, `contact_name`, and `profile.category/subcategory` + `profile.addresses.registered` (street1/street2/city/state/postal_code/country). The addresses block is mandatory per Razorpay; `franchisee_onboarding_service` fails early with a readable `RuntimeError` when `address`, `city`, `state`, or `pincode` is missing on the Franchisee record. Razorpay SDK errors are caught in `routers/franchisees.onboard_to_razorpay` and returned as HTTP 400 with the Razorpay message so the admin UI shows the actual cause, not "Internal Server Error". Razorpay emails the franchisee a KYC invite directly; no hosted onboarding URL is relied on.
  - Test/Live mode support
- **`monitoring_service.py`** - Sentry + New Relic integration
  - `@trace_transaction` decorator for OCPP message tracing
  - `MetricsCollector`, `OCPPMetrics`, `SentryHelper` classes
  - **W6 metrics for failure-mode alerting**: `record_disconnect_suspended`, `record_disconnect_stopped`, `record_zero_energy_stopped`, `record_billing_failed`, `record_stale_suspended_swept` — all paired with `Custom/OCPP/...` counters and structured events. Linked from runbooks in `docs/runbooks/`.
- **`storage_service.py`** - **Firmware file storage and management**
  - Local filesystem storage in `/backend/firmware_files/`
  - MD5 checksum calculation for integrity
  - Download URL generation for OCPP UpdateFirmware
  - File naming: `{version}_{original_filename}`
  - Static serving via `/firmware/{filename}` endpoint
  - Volume is a Docker named volume (`backend_firmware_{env}`). Production
    image has no `USER` directive — `docker-entrypoint.sh` starts as root,
    `chown`s `/app/firmware_files` to `app:app`, then `exec gosu app` to
    drop privileges. Heals pre-existing volumes whose root directory was
    seeded under a different user (the bug that broke staging firmware
    uploads). See `backend/Dockerfile` + `backend/docker-entrypoint.sh`.
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
    account with full payload: `reference_id=f"franchisee_{id}"`,
    `legal_business_name`, `customer_facing_business_name`,
    `business_type` (mapped via `_BUSINESS_TYPE_MAP` from our
    `FranchiseeBusinessTypeEnum`), `contact_name`, `profile.category/
    subcategory` (utilities / electric_vehicle_charging). Fails fast
    with a `RuntimeError` if `business_type` is not yet set on the
    franchisee — admin must fill it via the Business Details edit
    dialog before calling onboarding. Persists any optional
    `hosted_onboarding_url` from the response (best-effort; Razorpay
    emails the franchisee directly regardless).
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
  - End-to-end UX: admin fills business details (business_type, PAN,
    GSTIN, etc.) via the Edit dialog on `/admin/franchisees/[id]`,
    clicks "Start Razorpay onboarding"; backend creates the linked
    account; Razorpay emails the franchisee a KYC invite directly;
    webhook handlers advance status as Razorpay progresses the KYC.
- **`franchisee_settlement_service.py`** - **Post-session franchisee payout**
  - `process_settlement(transaction_id)` runs from `transaction_finalizer`
    right after `process_qr_session_billing` returns (refund already
    issued). Creates a `CommissionLedgerEntry` with `idempotency_key=
    f"txn_{id}"` capturing the gross → net → franchisee_payout split.
    Immediately calls `initiate_transfer` if the franchisee is ACTIVE
    with a linked account and payout ≥ `MINIMUM_TRANSFER_AMOUNT` (₹1).
  - `calculate_settlement(...)` is the pure math: `net_excl_gst =
    gross - refund - pg_fee - gst_collected`; `platform_commission`
    and `tds_amount` come off that; `franchisee_payout` is what
    remains. `transfer_fee` is NOT deducted at calc time — it's
    populated after the fact from the `settlement.processed` webhook
    (Razorpay's actual per-transfer fee).
  - `initiate_transfer(entry)` calls
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

### Frontend Core (`/frontend/`)
- **`app/page.tsx`** - Role-based dashboard (different for ADMIN vs USER)
- **`app/admin/`** - Complete admin interface for station/charger/user management
  - **`app/admin/qr-codes/page.tsx`** - **NEW** QR code list with create/close actions, revenue stats
  - **`app/admin/qr-codes/[id]/page.tsx`** - **NEW** QR detail with payment history, refund tracking, QR image
- **`app/my-charges/page.tsx`** - Public (no auth) page with charger map + transaction history. Top section: Leaflet map showing all stations with real-time availability (color-coded markers), user location, popup details, "Get Directions" to Google Maps. Bottom section: UPI ID lookup for paginated QR transactions, refund status, energy consumed
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
- **`contexts/AuthContext.tsx`** - Clerk auth wrapper with `isAuthReady`, `getToken`, global token access
- **`contexts/QueryClientProvider.tsx`** - TanStack Query setup
- **`contexts/ThemeContext.tsx`** - Light/dark/system theme management

### Key Configuration
- **`backend/requirements.txt`** - Python dependencies (FastAPI, python-ocpp, Tortoise ORM, etc.)
- **`frontend/package.json`** - Node dependencies (Next.js 15, React 19, Clerk, TanStack Query, etc.)
- **`backend/pyproject.toml`** - pytest configuration and Aerich migration settings

---

## Database Schema Quick Reference

### Core Tables with Relationships
```sql
-- User Management (Clerk Integration + UPI_GUEST)
user (id, clerk_user_id, phone_number, full_name, role, upi_vpa, auth_provider) -- USER/ADMIN roles, EMAIL/GOOGLE/CLERK/UPI_GUEST auth
wallet (id, user_id, balance, currency)
wallet_transaction (id, wallet_id, amount, type)

-- Charging Infrastructure
charging_station (id, name, latitude, longitude, address)
charger (id, charge_point_string_id, station_id, vendor, model, latest_status, last_heart_beat_time)
connector (id, charger_id, connector_id, connector_type, max_power_kw) -- connector_type: Type2, CCS, CHAdeMO, Socket
tariff (id, station_id, rate_per_kwh, gst_percent) -- gst_percent default 18.00, applied on top of energy charge

-- OCPP Transactions
transaction (id, user_id, charger_id, start_meter_kwh, end_meter_kwh, transaction_status, suspended_at, resumed_at, resume_count, energy_charge, gst_amount, total_billed)
meter_value (id, transaction_id, reading_kwh, current, voltage, power_kw)

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
  Response: { "data": [{ id, name, latitude, longitude, address, available_chargers, total_chargers, connector_types, connector_details, price_per_kwh }], "total" }

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