# OCPP 1.6 Charging Station Management System - Architecture Documentation

## Executive Summary

This document provides comprehensive technical documentation for a production-ready **Open Charge Point Protocol (OCPP) 1.6** compliant Charging Station Management System (CSMS). The system implements a full-stack solution for managing Electric Vehicle (EV) charging stations with real-time monitoring, remote control capabilities, role-based access control, and integrated financial management.

**System Version**: 3.1
**OCPP Compliance**: OCPP 1.6 Full Implementation
**Architecture**: Modern async Python backend with React web frontend + Capacitor mobile apps
**Authentication**: Clerk-powered JWT authentication with RBAC + UPI_GUEST for appless users
**Payments**: Razorpay (wallet top-up + QR-based appless charging with auto-refunds)
**Deployment**: Production-ready on AWS EC2 with Docker Compose (backend + frontend + nginx + Redis + PostgreSQL)
**Current Branch**: 57-qr-based-appless-transaction
**Last Updated**: March 2026

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Technology Stack](#technology-stack)
3. [Architecture Design](#architecture-design)
4. [Backend Components](#backend-components)
5. [Frontend Components](#frontend-components)
6. [Mobile App Components](#mobile-app-components)
7. [**NEW**: QR-Based Appless Charging](#qr-based-appless-charging)
8. [Database Schema](#database-schema)
9. [OCPP 1.6 Implementation](#ocpp-16-implementation)
10. [Authentication & Authorization](#authentication--authorization)
11. [API Documentation](#api-documentation)
12. [Real-Time Features](#real-time-features)
13. [User Experience Features](#user-experience-features)
14. [**NEW**: Docker Deployment & Infrastructure](#docker-deployment--infrastructure)
15. [Security & Compliance](#security--compliance)
16. [Testing Framework](#testing-framework)
17. [Performance & Scalability](#performance--scalability)
18. [Technical Debt & Known Issues](#technical-debt--known-issues)
19. [Deployment & Operations](#deployment--operations)
20. [Recent Changes & Updates](#recent-changes--updates)
21. [Future Roadmap](#future-roadmap)

---

## System Overview

### Business Context
The Electric Vehicle charging industry requires robust, standards-compliant management systems that can handle real-time communication with distributed charging hardware while providing both administrative oversight and seamless user experiences for EV drivers.

### System Purpose
This CSMS serves as the **Central System** in OCPP terminology, providing:
- **Real-time charging station monitoring** via OCPP WebSocket connections
- **Remote control capabilities** for charging infrastructure
- **Transaction management** with comprehensive energy consumption tracking
- **Financial integration** with wallet-based billing and retry mechanisms
- **Role-based access control** separating admin and user experiences
- **Interactive user interfaces** including station maps and QR code scanning
- **Comprehensive administrative dashboard** for operations management

### Key Capabilities
- ✅ **OCPP 1.6 Full Compliance** - All core messages and remote commands
- ✅ **Modern Authentication** - Clerk-powered JWT authentication with role-based access
- ✅ **Real-time Monitoring** - Live status updates and heartbeat tracking
- ✅ **Transaction Lifecycle Management** - From start to completion with detailed energy tracking
- ✅ **Remote Operations** - Start/stop charging, availability control via OCPP commands
- ✅ **Financial Integration** - Wallet system with automated billing and retry service
- ✅ **QR-Based Appless Charging** - Scan-and-pay UPI QR codes at chargers without needing an app or account
- ✅ **Budget Enforcement** - Real-time budget checking during MeterValues with auto-stop when budget exceeded
- ✅ **Automated Refunds** - Unused payment balance automatically refunded to customer via Razorpay
- ✅ **Transaction Resume** - Transactions survive charger reboots via SUSPENDED state with auto-stop timeout
- ✅ **Disconnect Handler** - Automatic transaction suspension on charger disconnect with configurable timeout and auto-stop billing
- ✅ **PostBootState Push** - Server pushes meter values and pending transaction state after every charger reboot
- ✅ **User Experience Features** - Interactive maps, QR scanning, mobile-responsive design
- ✅ **Scalable Architecture** - Redis-based connection management for horizontal scaling
- ✅ **Docker Production Deployment** - Complete Docker Compose stack with nginx, SSL, PostgreSQL, Redis
- ✅ **Production-Ready** - Comprehensive testing, error handling, Sentry monitoring, structured logging

---

## Technology Stack

### Backend Technologies (`/backend/`)
| Component | Technology | Version | Purpose |
|-----------|------------|---------|---------|
| **Web Framework** | FastAPI | 0.115.12 | High-performance async web framework |
| **OCPP Library** | python-ocpp | 2.0.0 | OCPP 1.6 protocol implementation |
| **Database ORM** | Tortoise ORM | 0.25.1 | Async database operations with PostgreSQL |
| **Authentication** | Clerk SDK | Latest | JWT validation and webhook handling |
| **Payment Gateway** | Razorpay SDK | 2.0.0 | **NEW** - Payment processing for wallet recharge |
| **Message Queue** | Redis | Latest | Connection state management and caching |
| **WebSocket** | Native FastAPI | - | Real-time OCPP communication |
| **Testing** | Pytest | 8.3.4 | Comprehensive test framework with async support |
| **Validation** | Pydantic | Latest | Data validation and serialization |
| **Migration** | Aerich | 0.9.1 | Database schema migrations |
| **Server** | Uvicorn | 0.34.3 | ASGI server for production deployment |

### Frontend Technologies (`/frontend/`)
| Component | Technology | Version | Purpose |
|-----------|------------|---------|---------|
| **Framework** | Next.js | 15.3.8 | React-based frontend with App Router |
| **Language** | TypeScript | 5.x | Type safety and developer experience |
| **Runtime** | React | 19.0.0 | Latest React with concurrent features |
| **Styling** | Tailwind CSS | v4 | Utility-first CSS framework |
| **UI Library** | Shadcn/ui | Latest | Radix UI-based component system |
| **State Management** | TanStack Query | 5.81.2 | Server state management and caching |
| **Authentication** | Clerk React | 6.29.0 | Client-side authentication |
| **Payment UI** | Razorpay Checkout.js | Latest (CDN) | **NEW** - Secure payment modal for wallet recharge |
| **Maps** | React Leaflet | 5.0.0 | Interactive station location maps |
| **QR Scanning** | ZXing | 0.21.3 | QR code scanning for charger access |
| **Charts** | Recharts | 3.2.1 | Energy consumption visualization |
| **Icons** | Lucide React | 0.523.0 | Consistent icon library |
| **Notifications** | Sonner | 2.0.5 | Toast notifications |

### Infrastructure & DevOps
- **Database**: PostgreSQL with SSL (Tortoise ORM, AsyncPG driver)
- **Cache/Queue**: Redis for real-time connection state + QR session caching
- **Authentication**: Clerk for user management and JWT + UPI_GUEST for appless users
- **Deployment**: AWS EC2 with Docker Compose (backend, frontend, nginx, redis, postgres)
- **Reverse Proxy**: Nginx with SSL termination, WebSocket proxying, rate limiting
- **Monitoring**: Sentry (error tracking) + New Relic (APM) + structured logging with correlation IDs
- **Error Handling**: Comprehensive async error boundaries
- **Containerization**: Docker multi-stage builds for backend (Python) and frontend (Next.js)

---

## Architecture Design

### High-Level Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│                 │    │                 │    │                 │
│  EV Charging    │◄──►│  OCPP Central   │◄──►│   Next.js       │
│  Stations       │    │  System (CSMS)  │    │  Web App        │
│  (OCPP 1.6)     │    │   (FastAPI)     │    │ (Admin + User)  │
│                 │    │                 │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
        │                       │                       │
        │                       │                ┌─────────────┐
        │               ┌───────┴───────┐        │    Clerk    │
        │               │               │        │   Auth      │
        └───────────────┤  PostgreSQL   ├────────┤  Service    │
                        │   Database    │        │             │
                        │               │        └─────────────┘
                        └───────────────┘
                               │
                        ┌─────────────┐
                        │    Redis    │
                        │ Connection  │
                        │   State     │
                        └─────────────┘
```

### Component Interaction Flow

1. **OCPP Charging Stations** connect via WebSocket to `/ocpp/{charge_point_id}`
2. **Central System** validates connections against registered chargers in database
3. **Redis** tracks connection states for real-time status monitoring + QR session budget caching
4. **PostgreSQL** stores all persistent data (transactions, logs, user data, QR payments, configurations)
5. **Clerk** manages user authentication and role-based access control
6. **Razorpay** handles UPI QR code generation, payment processing, webhooks, and refunds
7. **Next.js Frontend** provides both admin dashboard and user interfaces
8. **Real-time Updates** flow through WebSocket (OCPP) and polling (frontend)
9. **QR Payment Flow**: Customer scans UPI QR → Razorpay webhook → user resolution → RemoteStartTransaction → budget-enforced charging → auto-refund of unused balance

### Design Patterns
- **Event-Driven Architecture**: OCPP message handlers with async processing
- **Repository Pattern**: CRUD operations abstracted in service layers
- **Adapter Pattern**: WebSocket adapters for OCPP library compatibility
- **Observer Pattern**: Real-time updates with polling and caching mechanisms
- **State Machine**: Transaction status management with well-defined transitions
- **Role-Based Access Control**: Comprehensive RBAC throughout the application

---

## Backend Components

### Core Application Files

#### Main Application (`backend/main.py`)
**Purpose**: FastAPI application entry point with complete OCPP WebSocket handling

**Key Features**:
- **WebSocket Endpoint**: `/ocpp/{charge_point_id}` for OCPP charge point connections
- **CORS Configuration**: Production and development origin support
- **Connection Management**: Redis-backed connection state tracking with heartbeat monitoring
- **Message Logging**: Complete OCPP message audit trail with correlation IDs
- **Async Processing**: Full async/await pattern throughout

**Critical OCPP Message Handlers**:
- `on_boot_notification()`: Charger registration, transaction suspend/resume with auto-stop timeout
- `on_heartbeat()`: Connection liveness with 90-second timeout
- `on_status_notification()`: Real-time charger status updates with error tracking and transaction failure detection
- `on_start_transaction()`: Transaction initiation with user validation and QR payment linking
- `on_stop_transaction()`: Transaction completion with billing integration and QR refunds
- `on_meter_values()`: Real-time energy consumption tracking with QR budget enforcement

#### Database Models (`backend/models.py`)
**Purpose**: Complete database schema with OCPP-compliant enums and relationships

**Model Categories**:
1. **User Management**: User, Wallet, WalletTransaction, VehicleProfile
2. **Infrastructure**: ChargingStation, Charger, Connector, Tariff
3. **Operations**: Transaction, MeterValue
4. **QR Payments**: ChargerQRCode, QRPayment
5. **Firmware**: FirmwareFile, FirmwareUpdate
6. **Monitoring**: SignalQuality, ChargerError, AuditEvent, WebhookEvent
7. **System**: OCPPLog

**Key Enums**:
- `ChargerStatusEnum`: OCPP 1.6 compliant charge point statuses
- `TransactionStatusEnum`: Complete transaction lifecycle (STARTED, PENDING_START, RUNNING, SUSPENDED, PENDING_STOP, STOPPED, COMPLETED, CANCELLED, FAILED, BILLING_FAILED)
- `QRPaymentStatusEnum`: PAID, CHARGING, COMPLETED, REFUNDED, REFUND_FAILED, EXPIRED, FAILED
- `AuthProviderEnum`: EMAIL, GOOGLE, CLERK, UPI_GUEST
- `MessageDirectionEnum`: OCPP message direction tracking
- `UserRoleEnum`: USER and ADMIN roles for RBAC
- `WebhookSourceEnum`: CLERK, RAZORPAY for webhook event logging

### API Routing System (`backend/routers/`)

#### Authentication Router (`backend/routers/auth.py`)
**Endpoints**: `/auth/*`
**Purpose**: Authentication status and user profile management
- User profile retrieval and updates
- Role-based access validation

#### Station Management (`backend/routers/stations.py`)
**Endpoints**: `/api/admin/stations/*`
**Purpose**: Complete charging station lifecycle management
- CRUD operations with geographic data (latitude/longitude)
- Search and pagination support
- Cascade operations for associated chargers

#### Charger Management (`backend/routers/chargers.py`)
**Endpoints**: `/api/admin/chargers/*`
**Purpose**: Advanced OCPP charger operations and remote control
- Real-time connection status via Redis integration
- OCPP remote commands: RemoteStart/Stop, ChangeAvailability
- Bulk operations for dashboard efficiency
- Connection state monitoring

#### Transaction Management (`backend/routers/transactions.py`)
**Endpoints**: `/api/admin/transactions/*`
**Purpose**: Complete transaction lifecycle and energy tracking
- Transaction history with filtering and pagination
- Meter value aggregation for energy consumption charts
- Admin override capabilities for transaction management

#### User Management (`backend/routers/users.py`)
**Endpoints**: `/users/*`
**Purpose**: User account management and wallet operations
- User profile management with transaction history
- Wallet balance and transaction tracking
- Admin-only user management capabilities
- **NEW**: User transaction pages with pagination
- **NEW**: Wallet transaction history with running balance
- **NEW**: Transaction summary statistics

#### Firmware Management (`backend/routers/firmware.py`)
**Endpoints**: `/api/admin/firmware/*` (admin) and `/api/firmware/*` (public)
**Purpose**: Firmware update lifecycle for OCPP and polling chargers, with BootNotification-driven completion and CSMS-side exponential backoff retries.

**Admin Endpoints**:
- `POST /api/admin/firmware/upload` - Upload firmware files (.bin, .hex, .fw); stored on S3 (`AWS_S3_FIRMWARE_BUCKET`).
- `GET /api/admin/firmware` - List firmware files
- `DELETE /api/admin/firmware/{id}` - Soft delete (`is_active=False`)
- `POST /api/admin/firmware/chargers/{id}/update` - Schedule update; resets any existing row for this (charger, firmware) pair regardless of prior status.
- `POST /api/admin/firmware/bulk-update` - Bulk schedule
- `GET /api/admin/firmware/chargers/{id}/history` - History per charger
- `GET /api/admin/firmware/updates/status` - Dashboard (PENDING rows + counts)
- `POST /api/admin/firmware/updates/{id}/cancel` - Cancel a PENDING row that has not yet been attempted (`attempt_count == 0`)
- `POST /api/admin/firmware/updates/{id}/mark-installed` - Admin manual close for polling chargers (also updates `Charger.firmware_version`)
- `POST /api/admin/firmware/updates/{id}/mark-failed` - Admin manual close (does not touch `Charger.firmware_version`)

**Public Endpoint**:
- `GET /api/firmware/latest?external_charger_id=X&current_firmware_version=Y` - Polling chargers fetch their pending update here. When `current_firmware_version` matches the pending target, the server auto-closes the row as INSTALLED.

**State machine (v2, migration 35)**:
4 states only — **PENDING / INSTALLED / FAILED / CANCELLED**. Intermediate states (DOWNLOADING / DOWNLOADED / INSTALLING) and split failures (DOWNLOAD_FAILED / INSTALLATION_FAILED) were collapsed because they encoded signals (`FirmwareStatusNotification`) that aren't reliably delivered.

**Why BootNotification is the source of truth (CRITICAL — non-obvious)**:
Chargers using Quectel cellular modems (BG95/BG96, EC25, EG21/25 family) cannot reliably maintain the OCPP WSS connection during firmware download. The modem suspends WSS to free its single TLS context, or WSS keepalive starves under the download throughput. So `FirmwareStatusNotification: Downloading/Downloaded/Installing/Installed/DownloadFailed` may never arrive. **The only reliable completion signal is the BootNotification the charger sends after install + reboot, carrying its new `firmware_version`.** `FirmwareStatusNotification` handler (`main.py:1168+`) is therefore logging-only — it writes to OCPPLog but does not transition state.

**Retry semantics (CSMS-side)**:
- Each attempt = one `UpdateFirmware` command. Server records `attempt_count`, `last_attempt_at`.
- `handle_boot_notification(charger, reported_version)` runs from the BootNotification handler:
  - Match → INSTALLED (terminal)
  - Mismatch within `FIRMWARE_BOOT_DEBOUNCE_SECONDS` (default 300s) → ignore (charger may still be mid-download)
  - Mismatch outside debounce → attempt failed; schedule next via backoff
- Phase B timeout: if no BootNotification arrives within `FIRMWARE_ATTEMPT_TIMEOUT_SECONDS` (default 7200s/2h), the scheduler declares the attempt failed.
- Backoff schedule: **5min → 30min → 2h → 4h**. Capped by `FIRMWARE_MAX_ATTEMPTS` (default 5) AND `FIRMWARE_MAX_ELAPSED_SECONDS` (default 21600s/6h).
- Budget exhausted → FAILED. Admin must re-trigger to retry.

**Storage**:
- S3 with presigned GET URLs. TTL = `max(FIRMWARE_MAX_ELAPSED_SECONDS, 24h) + 1h` so a URL handed out at attempt 1 outlives the retry window.
- `FirmwareFile.s3_key` is the bucket key. `FirmwareFile.file_path` and the local `/firmware/{filename}` StaticFiles mount remain as legacy fallback for rows with `s3_key=NULL`.

**OCPP flow (post-redesign)**:
1. Admin triggers update → row = PENDING.
2. Background scheduler waits for charger online + idle, then sends OCPP `UpdateFirmware` with a presigned S3 URL.
3. WS drops within seconds (expected — `expected_ws_drop_until` flag suppresses alerts for 30 min).
4. Charger downloads, installs, reboots.
5. Post-install BootNotification arrives with new `firmware_version` → row → INSTALLED.
6. If BootNotification reports the old version (outside the 5-min debounce) OR no boot within 2h → attempt failed; scheduler picks the next backoff bucket.
7. After 5 attempts or 6h elapsed, row → FAILED.

**Polling flow (out-of-network chargers)**:
1. Charger polls `GET /api/firmware/latest?external_charger_id=...&current_firmware_version=...` every ~30 min.
2. Server returns the PENDING row's URL + checksum.
3. Charger downloads + installs out-of-band.
4. Next poll carries the new version → server auto-marks INSTALLED. If the charger can't report version, admin uses `mark-installed` to close the row.

**Env vars** (defaults shown; configurable in all three docker-compose files):
- `FIRMWARE_MAX_ATTEMPTS=5`
- `FIRMWARE_MAX_ELAPSED_SECONDS=21600` (6h wall-clock)
- `FIRMWARE_ATTEMPT_TIMEOUT_SECONDS=7200` (2h per-attempt timeout)
- `FIRMWARE_BOOT_DEBOUNCE_SECONDS=300` (5min)
- `AWS_S3_FIRMWARE_BUCKET=...`
- `FIRMWARE_PUBLIC_BASE_URL=...` (legacy fallback URL when `s3_key` is null)

#### QR Code Management (`backend/routers/qr_codes.py`)
**Endpoints**: `/api/admin/qr-codes/*`
**Purpose**: **NEW** - Admin CRUD for Razorpay UPI QR codes linked to chargers

**Endpoints**:
- `POST /api/admin/qr-codes` - Create QR code for a charger (calls Razorpay API)
- `GET /api/admin/qr-codes` - List QR codes with pagination, search, status filter
- `GET /api/admin/qr-codes/{qr_id}` - QR code detail with payment stats (count, revenue, refunds)
- `POST /api/admin/qr-codes/{qr_id}/close` - Deactivate QR code (closes on Razorpay)
- `GET /api/admin/qr-codes/{qr_id}/payments` - Paginated payment history for a QR code
- `GET /api/admin/qr-codes/charger/{charger_id}` - Get QR code for a specific charger

**Key Features**:
- Revenue aggregation per QR code (sum of COMPLETED, REFUNDED, CHARGING payments)
- Status badges: PAID, CHARGING, COMPLETED, REFUNDED, FAILED, REFUND_FAILED, EXPIRED
- QR code image URL and short URL from Razorpay for printing/display

#### Public Stations (`backend/routers/public_stations.py`)
**Endpoints**: `/api/public/stations/*`
**Purpose**: Authenticated station and charger discovery for user-facing pages
- List stations with charger availability counts (requires USER auth)
- Get station details by ID (requires USER auth)
- Shared helper `_fetch_stations_with_availability()` provides Redis+heartbeat filtering, connector aggregation, and tariff lookup for both authenticated and public endpoints
- **Tariff display (post-ADR 0003, 2026-05-18)**: tariff is per-charger. `Tariff.tariff_per_kwh_all_in` is the operator-typed, customer-displayed source of truth; `Tariff.rate_per_kwh` is back-derived. `StationChargerInfo` carries `tariff_per_kwh` (back-derived), `tariff_per_kwh_all_in`, `tariff_gst_percent`; `PublicStationResponse` carries station-level `min/max_price_per_kwh_all_in` (collapse to a single value when uniform). `price_per_kwh` is preserved for compat as the min back-derived rate. Backend helpers live in `backend/services/tariff_utils.py` (`back_derive_rate_per_kwh`, `compute_station_tariff_range`). Frontend renders the all-in figure with an `(all-inclusive)` label via `formatTariffRangeAllIn` in `frontend/lib/utils.ts`. The admin chargers form (`frontend/app/admin/chargers/page.tsx`) takes a single `tariff_per_kwh_all_in` input bounded to ₹1.0–100.0 and renders a live `TariffBreakdownPreview` (computed client-side via `breakdownAllInTariff`) showing the back-derived `rate_per_kwh`, the gateway-fee per kWh, and the GST per kWh — mirroring the backend back-derivation so the operator sees exactly what will be stored.

- **Invoice tariff snapshot (post-2026-05-19)**: `GSTInvoice.tariff_per_kwh_all_in` (nullable, added by migration 38) captures the operator's `Tariff.tariff_per_kwh_all_in` at the moment of issuance. The PDF renders this snapshot in the `Tariff / kWh (Including Taxes and Gateway Charges)` column when present, so the invoice always shows the operator's promised customer-facing rate — even if the operator later changes the tariff. Legacy invoices (pre-cutover) have NULL and fall back to the GST-only-effective `tariff_rate_incl_tax` field with the legacy column header `Tariff / kWh (Including Taxes)`. See ADR 0003 "Invoice display."

- **Migration cutover note**: migration 36 shrinks every `Tariff.rate_per_kwh` by 2% so customer-facing displayed prices stay constant; the franchisee absorbs the 2% on legacy tariffs until they re-save via the new API. The originally-planned `operator_set_all_in_at` audit column + `/api/admin/tariffs/legacy` banner endpoint were dropped at the time of cutover (two live chargers — ops handles re-entry manually). See ADR 0003 for the conditions to add the banner back.

- **`ConnectorInfo` per-plug-type schema (post-2026-05-21, /my-charges modal redesign)**: `_aggregate_connectors` now emits per-plug-type `ready_count` / `in_use_count` / `out_of_service_count` (3-bucket mapping from `ChargerStatusEnum` via `_status_bucket`: AVAILABLE→ready, PREPARING/CHARGING/SUSPENDED_*/FINISHING→in_use, FAULTED/UNAVAILABLE/RESERVED→out_of_service) plus per-plug-type `min_tariff_all_in` / `max_tariff_all_in` (collapse to single value when uniform; falls back to global tariff for chargers without their own). Legacy `available_count` / `total_count` are still emitted (=`ready_count` / total) for `/stations` and the leaflet popup which still render the simple "X/Y available" form. The customer-facing `/my-charges` station modal uses the new fields under a "Chargers" heading (1 charger ↔ 1 connector working fleet invariant per `CONTEXT.md`) with a single "all prices include GST & fees" footnote; the station-wide tariff range tile and the "Available Chargers" headline tile were dropped in the same change.

#### Public Station Map (`backend/routers/public_station_map.py`)
**Endpoints**: `GET /api/public/stations/map`
**Purpose**: Public (no auth) charger map data with real-time availability
- Returns station-level aggregated data (no individual charger IDs exposed)
- In-memory per-IP rate limiting (20 requests per 60-second window)
- Reuses `_fetch_stations_with_availability()` from `public_stations.py`
- Frontend: Leaflet map on `/my-charges` page
- Carries the same station-level `min/max_price_per_kwh_incl_tax` as `/api/public/stations` but deliberately omits per-charger detail (no `charge_point_string_id`). Popup/list/my-charges modal render the range string `₹min–₹max/kWh (incl. GST)`.

#### Public QR Transaction History (`backend/routers/public_qr_transactions.py`)
**Endpoints**: `GET /api/public/qr-transactions?vpa=xxx&page=1&limit=10&status=COMPLETED`
**Purpose**: Public (no auth) endpoint for QR users to look up transaction history by UPI ID
- Paginated list of QR payments filtered by `customer_vpa` (exact match, case-insensitive)
- Returns amount paid, status, energy consumed, duration, charger name, refund info
- Minimal data exposure: omits customer PII and internal DB IDs
- VPA format validation (`xxx@yyy`)
- Frontend page: `/my-charges` (public route in Clerk middleware)
- **Refund lifecycle surface (2026-05-21, ADR 0005)**: response now carries `razorpay_refund_id`, `razorpay_refund_speed_processed`, `refund_processed_at`, `refund_failure_reason`. The frontend renders a 3-state lifecycle (Initiated / Sent to bank / Failed) with speed-conditional wording on the terminal state — "Refunded to your account on `<date>`" when `speed_processed == "instant"` (UPI/IMPS is real-time, so `refund.processed` ≈ customer-side credit) vs. "Sent to your bank on `<date>` — usually credits within 5–10 working days" when `speed_processed == "normal"` (NEFT/card reversal, Razorpay genuinely cannot confirm bank settlement). The `razorpay_refund_id` is shown collapsed as a "Ref:" line for support traces.

#### Public QR Active Sessions (`backend/routers/public_qr_active_sessions.py`)
**Endpoints**: `GET /api/public/qr-active-sessions?vpa=xxx`
**Purpose**: Live view of in-progress QR sessions for a customer, identified by their UPI VPA. Powers the active-session card on `/my-charges`.

- No auth — VPA is the implicit identifier; same trust model as `/api/public/qr-transactions`. **Read-only by design — see ADR 0006**: no remote-stop or other action endpoint is exposed because VPAs are not credentials (they appear on UPI receipts and screenshots customers freely share). Adding any state-mutating action behind a VPA check would create a grief-stop attack surface that rate-limiting only paper-overs.
- Same 20 req/60s/IP rate limit as the history endpoint, keyed `public_qr_active_sessions:{ip}` in Redis. VPA validation pattern lives in `backend/core/validators.py` (single source for both QR routers).
- **Canonical sub-state classifier**: `services/qr_session_state.customer_sub_state(qr_payment, transaction, stale_threshold_seconds=...)` is the single source of truth for "is this QR session active and in which sub-state?". Returns one of `waiting` / `charging` / `paused` / `stopping`, or `None` (exclude). The endpoint, watchdog, and any future caller should import this rather than re-encoding the QR/transaction state mapping.
- For `charging` / `paused` / `stopping` rows, the endpoint computes live KPIs **entirely from the `qr_session:{txn_id}` Redis row** — no per-session MeterValue DB query on the hot path. The cache row carries `tariff_rate` / `gst_percent` / `platform_fee` (synthetic) / `budget_limit_paise` / `start_meter_kwh` (stamped at StartTransaction) PLUS `latest_reading_kwh` / `latest_power_kw` / `latest_meter_at` (re-stamped by `QRPaymentService.check_budget_and_auto_stop` on every MeterValues frame — 2026-05-22, Option 1 of review item #4). Computed fields: `energy_kwh`, `spent_so_far` = `energy × rate × (1 + gst/100) + synthetic_platform_fee`, `refund_if_stopped_now` = `max(0, amount_paid - spent_so_far)`, `power_kw`. Pre-first-frame (cache row exists but `latest_reading_kwh` is absent) or cache-rebuild scenarios fall back to a one-row MeterValue query and increment `Custom/ActiveSession/MeterSnapshotDbFallback`. `waiting` entries instead carry `stale_threshold_seconds` (remaining seconds until the stale-watchdog auto-refund fires).
- **Cache contract (issue 05, 2026-05-21):** the `qr_session:{txn_id}` Redis row stores Decimal fields as strings (`amount_paid`, `platform_fee`, `tariff_rate`, `gst_percent`, `start_meter_kwh`), not floats. Readers parse via `Decimal(value)`. Legacy in-flight rows pre-2026-05-21 wrote floats — readers accept those via `Decimal(str(value))` for one TTL window (24h). On cache miss the endpoint AND `QRPaymentService.check_budget_and_auto_stop` log a structured WARNING and increment a counter (`Custom/ActiveSession/CacheMiss` and `Custom/QrSession/BudgetCheckCacheMiss` respectively) so ops can detect Redis instability or operator-edits-mid-session. The cache-miss path uses the **current** Tariff (intentional, matches final-billing math — see issue 05 / ADR 0005 area discussion).
- **Hardening (issue 04, 2026-05-21):** per-row classification + KPI computation is wrapped in `try/except`; one bad row logs + increments `Custom/ActiveSession/SessionComputeError` and is skipped without breaking the rest of the response. Per-request counter `Custom/ActiveSession/Request` and per-sub-state breakdown `Custom/ActiveSession/SubState/<waiting|charging|paused|stopping>` are emitted on every successful response.
- Frontend integration: `frontend/lib/queries/public-qr-active-sessions.ts` polls **adaptively** — 15s when at least one session is active, 60s when the response is empty — and pauses entirely when `document.visibilityState !== "visible"`. Frontend components live in `frontend/app/my-charges/_components/` (`ActiveSessionCard`, `ActiveSessionSkeleton`, `ActiveSessionsError`, `RefundLifecycle`, `TransactionCard`, `ChargerRow`). The 1-second duration tick is driven by a module-level **shared clock singleton** in `frontend/lib/hooks/useNowTick.ts` — first subscriber starts the interval, last unsubscriber tears it down, N hook callers = 1 timer. Multi-session VPAs render as a stacked list. First-load shows a skeleton; subsequent polls update silently. A retry-able error banner appears only when the query has no last-good response to fall back to — transient poll failures with cached data render silently. VPA persistence uses the namespaced `localStorage["voltlync.myCharges.lastVpa"]` key (with one-time migration from the pre-namespacing `voltlync.lastVpa`).

#### Webhook Handler (`backend/routers/webhooks.py`)
**Endpoints**: `/webhooks/*`
**Purpose**: Clerk webhook processing for user lifecycle events + Razorpay payment webhooks
- User creation and role assignment automation (Clerk)
- Webhook signature validation (Clerk SVIX + Razorpay HMAC-SHA256)
- **NEW**: `POST /webhooks/razorpay` - Handles `payment.captured`, `payment.failed`, `order.paid`, **`qr_code.credited`**, `refund.*`
- Routes `qr_code.credited` events to `QRPaymentService.handle_qr_payment()` for appless charging
- **Refund lifecycle (`handle_refund_event`)** handles three Razorpay events: `refund.processed` stamps `refund_processed_at` and captures `speed_processed` onto the row; `refund.failed` records the bank/error reason into `refund_failure_reason`; **`refund.speed_changed` (added 2026-05-21)** updates `razorpay_refund_speed_processed` when Razorpay silently downgrades instant→normal (or upgrades), so the customer-facing `/my-charges` ETA stays honest per ADR 0005. Razorpay does NOT emit any event confirming the refund has actually credited the customer's source bank account — `refund.processed` is the terminal Razorpay-side signal and for normal-speed refunds the 5–10 working-day issuing-bank settlement is outside Razorpay's visibility.
- **Cross-environment handling**: All handlers gracefully skip "not found" transactions (return 200, log warning) since production and staging share the same Razorpay live keys and both receive all webhook events. Only real errors (DB, API) return 500 for Razorpay retry.

### Business Logic Services (`backend/services/`)

#### Wallet Service (`backend/services/wallet_service.py`)
**Purpose**: Financial operations and billing management

**Key Features**:
- Transaction billing calculation based on energy consumption
- Wallet balance validation and deduction
- Automated retry mechanism for failed billing
- Integration with payment gateways (Razorpay)
- **NEW: Zero energy consumption handling** - No billing for 0 kWh transactions
- Wallet top-up processing with idempotency checks

**Methods**:
- `process_transaction_billing()`: Main billing workflow with atomic database transactions
- `calculate_billing_amount()`: Energy-based cost calculation with GST:
  - `energy_charge = energy_kwh × rate_per_kwh`
  - `gst_amount = energy_charge × gst_percent / 100` (default 18%)
  - `total_billed = energy_charge + gst_amount`
- `deduct_from_wallet()`: Secure balance deduction with SELECT FOR UPDATE locking (deducts `total_billed`)
- `process_wallet_topup()`: **NEW** - Handle wallet recharge from payment gateway

**Billing Logic**:
```python
if energy_consumed_kwh == 0:
    return (True, "No energy consumed", Decimal('0.00'))
# Proceed with normal billing for energy > 0
energy_charge = energy_kwh * rate_per_kwh
gst_amount = energy_charge * gst_percent / 100   # GST on energy cost only
total_billed = energy_charge + gst_amount         # Wallet deducts total_billed
```

**Internal-role skip (ADR 0004, added 2026-05-19)**: Before the QR / idempotency / energy / tariff checks, `_do_transaction_billing` resolves the initiator's `User.role` and returns immediately when it is in `core.roles.INTERNAL_ROLES` (`{ADMIN, FRANCHISEE}`). The session is set to `COMPLETED`, an awaited `transaction.status_changed` audit row is written with `trigger="InternalRoleSkip"`, and `Custom/Wallet/InternalRoleSkipped` is incremented. The mirror skip in `WalletSessionService.cache_session_on_start` (`Custom/WalletSession/InternalRoleSkipped`) ensures no `wallet_session:{txn_id}` Redis row is snapshotted. `services/invoice_service.py` was already gating GST invoice issuance on the same role set. The audit log is awaited (not `safe_create_task`) so it joins the same `@atomic` transaction — a spawned task would inherit the in-progress connection context which is unusable after the atomic exits. See `docs/adr/0004-internal-role-sessions-are-operational.md`.

**Internal-role wallet creation gate**: `routers/webhooks.py:handle_user_created` calls `Wallet.create(user=user)` only when `user_role not in INTERNAL_ROLES`. This pairs with the runtime skip above — the runtime skip is defense-in-depth against any legacy wallet that exists, the creation gate is the prevention going forward. One-shot SQL deleted the historical backfilled wallets on 2026-05-19: dev had 2 (user IDs 2, 8), staging had 9 (user IDs 12, 16, 19, 20, 22, 23, 24, 31, 39). Prod runs on the next `deploy`-branch push.

**Zero-energy watchdog Decimal serialization fix (2026-05-20)**: The MeterValues parser at `main.py:1075` constructs `reading_kwh` as `Decimal(str(value))`. This Decimal was passed through to `services/zero_energy_watchdog.check_zero_energy`, stuffed into a dict, and handed to `redis_manager.set_zero_energy_state` which serialised it via `json.dumps(data)` — no encoder for Decimal. Result: every MeterValues frame of every active session logged `Object of type Decimal is not JSON serializable` (223 occurrences in a recent staging log window) and the watchdog's tracking state never persisted. Two-layer fix: (1) the watchdog now does `reading_kwh = float(reading_kwh)` at entry — kWh precision down to the milliwatt-hour is well above what the minute-scale stall check needs; (2) all four `json.dumps(data)` writers in `redis_manager.py` (`set_qr_session`, `set_wallet_session`, `set_zero_energy_state`, `set_socket_grace_period`) now pass `default=str` as defense for any future Decimal-bearing field. Regression tests in `tests/test_zero_energy_watchdog.py` (`TestDecimalReadingKwh`, `TestRedisManagerDefaultStrDefense`).

#### Billing Retry Service (`backend/services/billing_retry_service.py`)
**Purpose**: Background service for recovering failed transactions and cleaning up stale state

**Features**:
- **Runs every 30 minutes** as a background asyncio loop
- Automatic retry for BILLING_FAILED transactions
- **QR Refund Retry**: Retries REFUND_FAILED QR payments via Razorpay
- **Orphaned QR Cleanup**: Detects and refunds QR payments stuck in PAID status (no transaction linked)
- **Stale Suspended Cleanup**: Auto-stops SUSPENDED transactions older than 5 hours with billing + QR refund
- Comprehensive error logging with per-item error handling (one failure doesn't block others)

**Recent Enhancement**: Zero Charged Transaction Handling
- Transactions with 0 kWh energy consumption are now handled gracefully
- No wallet deduction for zero-energy sessions
- Transaction status: COMPLETED (not BILLING_FAILED)
- Handles test/aborted sessions without billing errors

#### QR Payment Service (`backend/services/qr_payment_service.py`)
**Purpose**: **NEW** - Complete lifecycle management for QR-based appless charging sessions

**Key Methods**:
```python
class QRPaymentService:
    async def handle_qr_payment(webhook_data: dict) -> dict
        """Main entry point: idempotency check → staleness check → user resolution → charging trigger"""

    async def find_or_create_user_from_payment(phone, vpa, name) -> User
        """Priority: phone match → VPA match → create UPI_GUEST → system guest fallback"""

    async def link_transaction_to_qr_payment(transaction_id, charger_id, user_id) -> QRPayment
        """Called from StartTransaction: links OCPP transaction to QR payment, caches budget in Redis"""

    async def check_budget_and_auto_stop(transaction_id, reading_kwh)
        """Called from MeterValues: calculates cost vs budget, schedules RemoteStop if exceeded"""

    async def process_qr_session_billing(transaction_id)
        """Called from StopTransaction: calculates final cost (capped at budget),
        issues partial refund for unused balance.

        Over-consumption cap: the charger keeps delivering for a few seconds
        after we send RemoteStopTransaction, so metered kWh can overshoot the
        Redis-enforced budget. Billable energy_cost is capped at the budgeted
        pre-tax ceiling = (amount_paid - platform_fee) / (1 + gst%/100). The
        over-delivered energy is absorbed by the operator and logged as a
        WARNING. transaction.energy_consumed_kwh remains the authoritative
        meter reading; only billable values on qr_payment and on the invoice
        reflect the cap. The customer-facing invoice's `energy_consumed_kwh`
        column is the *billable* kWh (energy_charge / tariff_rate) so the
        line-item math reconciles."""

    async def handle_charging_failure(transaction_id)
        """Handles failures: sets status=FAILED, issues full refund"""
```

**Charger control surface — admin vs franchisee API divergence**: two endpoints expose ChangeAvailability, deliberately with different contracts:
- `POST /api/admin/chargers/{id}/change-availability?type=Operative|Inoperative&connector_id=0` — admin endpoint, OCPP-aligned vocabulary. `connector_id` is validated to be `0` (whole-charger only); per-connector toggle isn't a product feature today. The query-param shape preserves OCPP terminology so admins debugging via curl or audit logs see exactly what was sent to the charger.
- `POST /api/franchisee/chargers/{id}/change-availability?available=true|false` — franchisee endpoint, operator-intuitive boolean. Internally maps to OCPP Operative/Inoperative and hardcodes `connector_id=0`.

This divergence is intentional. Admins debug at the OCPP layer and want explicit Operative/Inoperative terminology; franchisees want a self-serve on/off toggle. A future contributor who tries to "DRY" them into one shape will lose either the admin debugging vocabulary or the franchisee simplicity. Frontend mirrors the split — `lib/api-services.ts:chargerService.changeAvailability` (admin) vs `franchiseeService.changeAvailability` (franchisee).

The frontend's `useChangeAvailability` hook (admin) branches on the OCPP response status (Accepted → success + keep optimistic update, Scheduled → info toast + revert optimistic, Rejected → error toast + revert). Per issue 01 of the availability-toggle-fixes batch.

**Charger creation atomicity (issue 05, post-2026-05-18)**: `routers/chargers.py:create_charger` wraps the three writes (`Charger.create`, `Connector.create` per connector input, `Tariff.create`) in `async with in_transaction()`. If any step raises, the whole creation rolls back — no orphan chargers with partial connector sets or no tariff. Two audit-log paths:
- **Happy path**: `action="charger.created"` written after the transaction commits.
- **Rollback path**: `action="charger.create_failed"` written inside the `except IntegrityError` branch with the input data + `failure_reason`. Operators can query `WHERE action IN ('charger.created', 'charger.create_failed')` to see every attempted onboarding. The audit write itself is best-effort — wrapped in its own try/except so a secondary audit failure doesn't mask the original 400.

**Configuration**:
- `RAZORPAY_PLATFORM_FEE_PERCENT`: 2.0% — **authoritative synthetic rate** used for every customer-facing calculation (post-ADR 0001). Validated at startup (issue 03) in four bands via `core.config.validate_platform_fee_percent`: `≤0` and `>10` refuse startup with `RuntimeError`; `>5` logs `ERROR` and proceeds (legitimately high — ops should confirm intent); `0–5` is the normal range with an info log. Configurable ceilings live in `core/config.py` as `PLATFORM_FEE_HARD_CEILING` (10) and `PLATFORM_FEE_SOFT_CEILING` (5). The actual Razorpay fee is still captured on the `QRPayment` row for ops/reconciliation but is no longer used for budget, refund, or invoice math.
- `QR_PAYMENT_PENDING_TIMEOUT`: 300 seconds (env var)

**Tariff back-calc identity drift check (issue 02, post-2026-05-18)**:
- `services/tariff_drift_check.py` exposes `find_drifting_tariffs(fee_percent, sample_size)` and `warn_on_tariff_identity_drift(fee_percent, logger)`. Invoked from `main.py` startup after DB init.
- Samples up to 10 `Tariff` rows. For each, verifies `back_derive_rate_per_kwh(all_in, gst, current_fee) ≈ stored_rate_per_kwh` within ±0.0002. Catches the H3 scenario: migration 36 baked in the 2% fee assumption, but `RAZORPAY_PLATFORM_FEE_PERCENT` was changed afterwards — legacy-backfilled rows now violate the identity until operators re-save them via the admin form.
- One `WARNING` log per drifting row (named by `tariff_id` / `charger_id` / drift magnitude). `Custom/Tariff/IdentityDrift` counter increments once per startup if any drift detected — not once per row, to avoid alert storms on fleet-wide env changes.
- Non-fatal: startup proceeds either way. Operators clear drift by re-entering the affected tariff via the admin form, which recomputes `rate_per_kwh` under the current env-var value.

**Synthetic platform fee policy (effective 2026-05-18, ADR 0001)**:
- Three helpers replace the old `_resolve_platform_fee`. Public helpers live in `services/tariff_utils.py` (the single home for synthetic-fee policy math + the back-derivation formula); the side-effect writer stays in `qr_payment_service.py` because it talks to the Razorpay SDK.
  - `synthetic_platform_fee(amount_paid)` (in `tariff_utils`) — pure function, returns `amount_paid × RAZORPAY_PLATFORM_FEE_PERCENT/100`. Drives budget cap, over-payment refund, and invoice gateway-charges line.
  - `synthetic_fee_split(amount_paid)` (in `tariff_utils`) — returns the (commission, GST) breakdown, treating the 2% as all-in: commission = `× 2/118`, GST = `total − commission` (residual, not independently rounded).
  - `_ensure_actual_fee_captured(qr_payment)` (in `qr_payment_service`) — side-effect writer: ensures the actual Razorpay fee lives on the `QRPayment` row (`platform_fee` / `razorpay_commission` / `razorpay_gst`). Priority: webhook > API fetch > 2% estimate fallback.
- `RAZORPAY_PLATFORM_FEE_PERCENT` itself lives in `backend/core/config.py` (project-level config). Read by `main.py` (startup validation), `routers/chargers.py` (back-derivation on POST/PATCH), and `tariff_utils.py` (synthetic-fee math). Re-exported from `qr_payment_service.py` for backwards compatibility.
- `GSTInvoice.gateway_charges` / `gateway_gst` snapshot the synthetic 2% split at issuance, NOT the QRPayment row's actual fee. Customers see a deterministic gateway-charges line regardless of what Razorpay actually charged.
- Variance between actual and synthetic is absorbed by VoltLync as P&L — queryable via `SUM(qr_payment.platform_fee - 0.02 × amount_paid)`.

**Refund / over-consumption policy (effective 2026-05-13)**:
- **Positive balance** (customer paid more than they used) → **always refunded** via Razorpay, regardless of amount. The historical `MINIMUM_REFUND_AMOUNT` threshold has been removed.
- **Negative balance** (customer used more energy than they paid for, due to stop-signal latency) → **operator absorbs**. Existing budget cap on `energy_charge` stays; `Custom/QR/OverConsumptionCapped` / `Custom/QR/OverDeliveryKwh` metrics continue tracking magnitude.
- **Invariant**: `transaction_amount = total_amount + refund_amount` holds on every new QR invoice.

**Zero-energy refund policy (effective 2026-05-18, ADR 0002)**:
- When a QR session finalises with `energy_consumed_kwh ≤ 0`, `handle_charging_failure` → `_full_refund` issues a refund equal to the entire `amount_paid` (NOT `amount_paid - platform_fee` as in the pre-ADR behaviour).
- The actual Razorpay fee is still captured on the `QRPayment` row (`platform_fee` / `razorpay_commission` / `razorpay_gst`) for reconciliation, but the refund formula ignores it. VoltLync absorbs the Razorpay gateway fee and refund-processing fee as P&L loss — no service rendered, customer is made whole.
- No `GSTInvoice` is issued for zero-energy sessions (the invoice service short-circuits at `energy <= 0` in `generate_invoice`).
- Idempotency preserved: `razorpay_refund_id` guard prevents duplicate refunds on webhook retries.
- See `docs/adr/0002-zero-energy-full-refund.md` for the policy rationale and rejected alternatives.

**Razorpay instant refunds for full-refund flows (effective 2026-05-20, ADR 0002 amendment)**:
- All six `_full_refund` call sites — zero-energy at StopTransaction, stale payment, concurrent rejection on busy charger, charger not connected at start, RemoteStart failure, plug-in timeout — request Razorpay's `speed=optimum` mode. Customers see refunds in minutes instead of the default 5–7 working days.
- VoltLync absorbs Razorpay's per-refund instant fee (~₹5–₹6 + 18% GST per UPI refund) **in addition to** the original gateway fee. Same philosophy as the gateway-fee absorption: the customer experiencing a failure should not feel the cost of the failure.
- Partial unused-credit refunds in `process_qr_session_billing` remain on Razorpay's default `normal` speed. The partial-refund case = "here's your change" after service was rendered; not the same urgency as "we failed you."
- `speed=optimum` is best-effort. Razorpay falls back to `normal` server-side when rails or payment method don't support instant. The actual outcome is exposed in `speed_processed`, which `RazorpayService.refund_payment` logs on every refund.
- **Kill-switch env var**: `RAZORPAY_INSTANT_REFUND_ENABLED` (default `true`). Wired into `docker-compose.yml`, `docker-compose.staging.yml`, `docker-compose.prod.yml`, and the three `.env.*.example` files. Logged at startup in `backend/main.py`. Set to `false` and redeploy to revert all full refunds to normal speed without a code change.
- **Outcome persisted on the QRPayment row**: column `razorpay_refund_speed_processed` (VARCHAR(20), nullable; migration 40) holds Razorpay's reported `speed_processed` value (`"instant"` or `"normal"`) for every full-refund call — including the `RazorpayAlreadyRefundedError` reconciliation path when the existing-refund dict carries the field. NULL on partial refunds and on all pre-feature rows. The admin QR detail page (`/admin/qr-codes/[id]`) renders an `Instant` (green) or `Normal (5-7 days)` (gray) badge next to the refund amount when the column is non-null; customer-facing `/my-charges` is unchanged.
- **Monitoring counters** (emitted from `OCPPMetrics.record_refund_speed`, gated on `speed=optimum` actually being requested):
  - `Custom/QR/RefundInstantSucceeded` — `speed_processed == "instant"`.
  - `Custom/QR/RefundInstantFallback` — `speed_processed` came back as anything other than `"instant"` (typically `"normal"`).
  - Neither counter fires when `RAZORPAY_INSTANT_REFUND_ENABLED=false` (a normal-speed refund under the kill-switch is intentional, not a Razorpay-side fallback). A sudden spike in `RefundInstantFallback` is the operational alert for rail outages, account-level rate limits, or payment-method shifts.
  - A `QRRefundSpeed` New Relic event is also emitted with `charger_id`, `qr_payment_id`, and `speed_processed` for ad-hoc querying.

**Error Handling**:
- **Idempotency**: Checks `razorpay_payment_id` uniqueness before processing
- **Stale payments**: Refunds payments older than 5 minutes (customer likely left)
- **Double-payment guard**: Refunds if charger already has active transaction or pending QR payment
- **Charger disconnection**: Full refund if charger not connected
- **Plug-in timeout**: Background task polls 10s intervals for 5 minutes, refunds on timeout
- **RemoteStart failure**: Up to 2 retries with 5s delay, full refund if all fail
- **Budget exceeded**: Schedules RemoteStopTransaction as asyncio.create_task (avoids deadlock)

**Redis Session Cache**:
```
Key: qr_session:{transaction_id}
Value: {qr_payment_id, amount_paid, platform_fee, budget_limit, tariff_rate, gst_percent, start_meter_kwh, charger_id}
TTL: 86400 seconds (24 hours)
```

#### Razorpay Payment Service (`backend/services/razorpay_service.py`)
**Purpose**: **NEW** - Razorpay payment gateway integration for wallet recharge

**Key Features**:
- Secure payment order creation
- Payment signature verification (frontend callback)
- Webhook signature verification (server-to-server)
- Payment and order data fetching
- Refund support (future enhancement)
- Environment-based configuration (test/live mode)

**Security Features**:
- HMAC SHA256 signature verification
- Constant-time comparison to prevent timing attacks
- Raw payload validation for webhooks
- Idempotent payment processing

**Methods**:
```python
class RazorpayService:
    def create_order(amount: Decimal, receipt: str, notes: Dict) -> Dict
        """Create Razorpay order for wallet recharge"""

    def verify_payment_signature(order_id, payment_id, signature) -> bool
        """Verify payment authenticity using SDK"""

    def verify_webhook_signature(payload: bytes, signature: str) -> bool
        """Verify webhook events from Razorpay"""

    def fetch_payment(payment_id: str) -> Optional[Dict]
        """Get payment details for reconciliation"""

    def create_qr_code(charger_id: int, usage: str = "multiple_use") -> Dict
        """NEW: Create Razorpay UPI QR code linked to a charger"""

    def close_qr_code(qr_code_id: str) -> bool
        """NEW: Close/deactivate a Razorpay QR code"""

    def refund_payment(payment_id: str, amount: int = None) -> Dict
        """NEW: Issue full or partial refund via Razorpay"""
```

**Integration Points**:
- `/api/wallet/create-recharge`: Create payment order
- `/api/wallet/verify-payment`: Verify payment from frontend
- `/webhooks/razorpay`: Handle payment webhooks (primary source of truth)

**Payment Flow**:
```
User → Frontend Modal → Create Order → Razorpay Checkout → Payment
                                                              ↓
                                    ┌─────────────────────────┴──────────┐
                                    ▼                                    ▼
                          Frontend Verification                  Webhook Event
                          (Immediate feedback)                (Primary verification)
                                    │                                    │
                                    └──────────→ Wallet Credit ←─────────┘
                                              (Idempotent processing)
```

**Documentation**: See `/backend/docs/RAZORPAY_IMPLEMENTATION.md` for comprehensive details

#### Firmware Update Service (`backend/services/firmware_update_service.py`)
**Purpose**: Background service that processes pending firmware updates on startup and periodically

**Features**:
- Checks for FirmwareUpdate records in PENDING status
- Attempts to send OCPP UpdateFirmware commands to connected chargers
- Runs as background task started during app startup

#### Firmware Storage Service (`backend/services/storage_service.py`)
**Purpose**: Dual-mode storage for firmware files — S3 (primary) with a local-disk fallback for short-URL stopgap.

**Storage backend selection (effective 2026-05-20)**:
- `POST /api/admin/firmware/upload` reads `AWS_S3_FIRMWARE_BUCKET` at request time:
  - **Bucket set** (production-default behavior): bytes uploaded to S3, `FirmwareFile.s3_key` populated, `file_path=""`. `_try_trigger_update` dispatches `UpdateFirmware` with the ~1700-byte presigned URL.
  - **Bucket empty/unset** (stopgap for charger URL-parser limits): bytes written to `/app/firmware_files/{version}_{filename}` on the backend container, `s3_key=NULL`, `file_path` populated. `get_firmware_download_url_for_file` returns the legacy ~62-byte URL `{FIRMWARE_PUBLIC_BASE_URL}/firmware/{filename}` served by FastAPI's static-files mount (`main.py:158`) and proxied by nginx `location /firmware/`.
- Audit log records `storage_backend: "s3" | "local"` on every upload.
- Why: an EC2 instance-role-signed S3 presigned URL is ~1700 bytes due to the `X-Amz-Security-Token` (~1100 bytes of base64). Firmware on some chargers (Quectel modems) has a smaller URL-parse buffer. The stopgap lets ops flip to local-disk mode for staging without a code change — set `AWS_S3_FIRMWARE_BUCKET=""` and redeploy env. The proper long-term replacement is a backend proxy endpoint with a short opaque token (see follow-up issue).
- Security caveat: the legacy `/firmware/{filename}` URL has no signature/TTL — anyone who reaches the host with the right path can download the blob. Acceptable for staging; **must not be enabled on prod** without first landing the token-based proxy.

**Key Features**:
- Firmware file upload and storage — S3 in normal mode, `/app/firmware_files/` in stopgap mode
- MD5 checksum calculation for integrity verification
- Download URL generation for OCPP UpdateFirmware commands — automatically picks per-row based on `s3_key`
- File naming convention: `{version}_{original_filename}`
- Static file serving via `/firmware/{filename}` endpoint (always live; serves whatever is on disk regardless of S3 mode)

**Methods**:
```python
async def save_firmware_file(file: UploadFile, version: str) -> dict:
    """Save uploaded firmware with checksum calculation"""

def get_firmware_download_url(filename: str, base_url: str) -> str:
    """Generate public download URL for chargers"""

def calculate_checksum(file_path: str) -> str:
    """Calculate MD5 hash in chunks for large files"""

def delete_firmware_file(file_path: str) -> bool:
    """Remove physical firmware file from filesystem"""

def file_exists(file_path: str) -> bool:
    """Check if firmware file exists on disk"""
```

**File Security**:
- Extension whitelist: `.bin`, `.hex`, `.fw`
- Maximum file size: 100MB
- Unique version enforcement
- Soft deletion (keeps physical files after database soft delete)

**Volume ownership (production image)**:
- The `firmware_files/` directory is mounted as a Docker named volume
  (`backend_firmware_prod`, `backend_firmware_staging`) so uploads survive
  container recreation.
- Named volumes are seeded once at first mount; later image rebuilds do
  not re-apply ownership. To guarantee the app user (`uid 1001`) can
  write to the volume regardless of when it was created, the production
  image ships without a `USER` directive — `docker-entrypoint.sh` starts
  as root, `chown`s `/app/firmware_files` to `app:app`, then re-execs
  itself under `app` via `gosu`. The rest of the container lifecycle
  (migrations, uvicorn, healthcheck's CMD target) runs unprivileged.

**Static File Configuration** (`main.py`):
```python
FIRMWARE_DIR = os.path.join(os.path.dirname(__file__), "firmware_files")
app.mount("/firmware", StaticFiles(directory=FIRMWARE_DIR), name="firmware")
```

#### Data Retention Service (`backend/services/data_retention_service.py`)
**Purpose**: Background service for automated cleanup of old telemetry and log data

**Key Features**:
- Periodic cleanup of old signal quality data (default: 90 days retention)
- OCPP log cleanup (default: 90 days retention)
- Runs on configurable interval (default: every 24 hours)
- Graceful start/stop with async task management

**Configuration**:
```python
await start_data_retention_service(
    retention_days=90,           # Days to retain data
    cleanup_interval_hours=24    # Cleanup frequency
)
```

**Cleanup Targets**:
1. **Signal Quality Data**: Deletes `signal_quality` records older than retention period
2. **OCPP Logs**: Deletes `log` (OCPPLog) records older than retention period

**Monitoring**:
- Logs cleanup operations with record counts
- Error handling with retry logic (1 hour retry interval on failure)
- Graceful shutdown on service stop

#### Disconnect Handler (`backend/services/disconnect_handler.py`)
**Purpose**: Manages transaction suspension and auto-stop when a charger disconnects unexpectedly (power failure, network loss)

**Key Functions**:
```python
async def suspend_transactions_on_disconnect(charge_point_id: str) -> None
    """Called by ConnectionManager on charger disconnect. Suspends all active
    transactions (RUNNING, STARTED, PENDING_START, PENDING_STOP) and starts
    a configurable timeout for each."""

async def sweep_stale_suspended_transactions() -> None
    """Safety net called once at server startup. Finds SUSPENDED transactions
    older than the max timeout and auto-stops them (covers server restarts
    where in-memory timeout tasks were lost)."""
```

**Disconnect Flow**:
1. Heartbeat monitor detects charger silence (120s inactivity)
2. `ConnectionManager.force_disconnect()` fires registered callbacks
3. `suspend_transactions_on_disconnect()` sets all active transactions to SUSPENDED, records `suspended_at`
4. Starts a `DISCONNECT_SUSPEND_TIMEOUT` (default 180s) timer per transaction
5. **If charger reconnects** (BootNotification): timeout is invalidated via CAS guard (`suspended_at` comparison), and a new resume window starts
6. **If timeout expires**: transaction is auto-stopped with `stop_reason=DISCONNECT_TIMEOUT`, energy is calculated from the last MeterValue, and billing is processed

**Auto-Stop Billing** — delegated to `transaction_finalizer.finalize_stopped_transaction` (see below):
- Calculates energy from the last `MeterValue` record
- Processes wallet billing via `WalletService.process_transaction_billing()`
- Processes QR payment billing/refund via `QRPaymentService`
- Sets `BILLING_FAILED` status if billing errors occur
- Skips billing for zero-energy sessions
- Cleans up zero-energy redis state and pathological-flap counter

**CAS Guard for Timeout Safety**:
The disconnect timeout task uses a Compare-And-Swap pattern: it only acts if the transaction is still SUSPENDED with the same `suspended_at` timestamp. When BootNotification resets `suspended_at`, the old timeout becomes a no-op.

**Pathological-Flap Detection** (W5):
A naive disconnect cap would falsely terminate legitimate long sessions on flaky cellular sites (overnight charging on grid that drops every hour). Instead, the disconnect handler tracks **consecutive disconnects without energy progress** via an in-memory dict `_disconnect_reset_count[txn_id]`. The counter is:
- Initialized to 0 on first disconnect-suspend
- Incremented on every BootNotification reset of `suspended_at` (in `main.py` BootNotification handler)
- Zeroed by `zero_energy_watchdog.check_zero_energy` whenever MeterValues show real energy advancing
- Popped from the dict on transaction finalization

If the counter reaches `MAX_RESETS_WITHOUT_PROGRESS` (default 3), BootNotification stops resetting `suspended_at` and lets the existing timer fire. This caps the worst-case stuck-time at `3 × DISCONNECT_SUSPEND_TIMEOUT_SECONDS` for genuinely broken sessions while allowing healthy long sessions to flap freely.

**Configuration**:
| Variable | Default | Purpose |
|----------|---------|---------|
| `DISCONNECT_SUSPEND_TIMEOUT_SECONDS` | 180 | Seconds to wait after disconnect before auto-stopping |
| `SUSPEND_TIMEOUT_SECONDS` | 300 | Resume window after BootNotification resets the timeout |
| `MAX_DISCONNECT_RESETS_WITHOUT_PROGRESS` | 3 | Max BootNotification resets allowed without energy progress |

**Integration Points**:
- `ConnectionManager.register_on_disconnect()` -- wires up the callback
- `main.py` startup -- calls `sweep_stale_suspended_transactions()`
- `on_boot_notification()` -- resets `suspended_at` for already-SUSPENDED transactions (with W5 cap)

#### Transaction Finalizer (`backend/services/transaction_finalizer.py`)
**Purpose**: Single source of truth for stopping a transaction that timed out (rather than being stopped by a normal StopTransaction OCPP message). Replaces duplicated stop-and-bill logic that previously lived in `main.py:_suspend_timeout` and `disconnect_handler._stop_and_bill_transaction`.

**Public API**:
```python
async def finalize_stopped_transaction(
    transaction: Transaction,
    stop_reason: str,
) -> None
```

**Idempotent**: a transaction already in STOPPED / COMPLETED / BILLING_FAILED / FAILED is a no-op.

**Sequence**:
1. Calculate final energy from the latest `MeterValue`
2. Mark `transaction_status = STOPPED`, set `end_time` and `stop_reason`
3. Audit-log the transition
4. Record `OCPPDisconnectStopped` metric if `stop_reason == "DISCONNECT_TIMEOUT"`
5. Process wallet billing (skip if zero energy)
6. Process QR billing/refund
7. Clean up zero-energy redis state
8. Pop the disconnect-flap counter

**Used by**:
- `main.py:ChargePoint._suspend_timeout` (BootNotification suspend timeout, stop_reason=`SUSPENDED_TIMEOUT`)
- `disconnect_handler._disconnect_suspend_timeout` (disconnect timeout, stop_reason=`DISCONNECT_TIMEOUT`)
- `disconnect_handler.sweep_stale_suspended_transactions` (startup safety net, stop_reason=`STALE_SUSPEND_SWEEP`)
- `main.py:ChargePoint._handle_ongoing_transaction_on_boot` (BootNotification staleness guard, stop_reason=`STALE_RECONNECT`)
- `main.py:ChargePoint.on_meter_values` (MeterValues staleness guard, stop_reason=`STALE_RECONNECT`)
- `main.py:ChargePoint._handle_get_last_meter_value` (GetLastMeterValue staleness guard, stop_reason=`STALE_RECONNECT`)

##### Resume Staleness Guard

**Purpose**: defense-in-depth against the failure mode where `suspend_transactions_on_disconnect` does not run (swallowed exception in the broad `except`, callback not wired, race) or where its 180s `_disconnect_suspend_timeout` task dies (process restart) before firing. Without this guard, a charger that drops for an hour and reconnects can have its transaction suspended on BootNotification (edge-case branch) and immediately resumed by the next MeterValues — billing whatever the post-disconnect meter reads against the original session.

**Helper**:
```python
async def is_resume_too_stale(
    transaction: Transaction,
) -> Tuple[bool, Optional[float]]
```

Returns `(is_stale, gap_seconds)`. The gap is computed against the most recent of:
1. `transaction.suspended_at`
2. Latest `MeterValue.created_at` for this transaction
3. `transaction.start_time` (fallback when neither of the above exists)

A txn with no signals at all returns `(False, None)` — the helper defers to the caller's existing state checks rather than refusing speculatively.

**Threshold**: `MAX_RESUME_GAP_SECONDS=900` (15 min, configurable via env). Chosen to be comfortably above the existing 360s startup sweep cutoff so the guard never races with the primary finalize chain, yet small enough to prevent meaningful overcharging when it does fire.

**Call sites and behavior on stale**:
| Call site | Action when stale |
|---|---|
| `_handle_ongoing_transaction_on_boot` (BootNotification) | finalize, pop flap counter, return — no audit `transaction.suspended` log, no `_suspend_timeout` scheduled |
| `on_meter_values` (auto-resume) | finalize, return `call_result.MeterValues()` — the trailing meter value is **not** stored (would create `reading_kwh > end_meter_kwh` since `_calculate_final_energy` already snapshotted) |
| `_handle_get_last_meter_value` | finalize, return `DataTransfer(status="Rejected", data={"error": "Transaction expired due to long disconnect"})` so the firmware stops retrying |

**Audit log**: every guard hit emits `transaction.resume_blocked` with `actor_type=system`, `changes={trigger, gap_seconds, reason: "STALE_RECONNECT"[, previous_status]}`. Pair this with the existing `transaction.finalized` event (stop_reason `STALE_RECONNECT`) to forensically reconstruct which resume path tripped.

**Operational signal**: any production hit of `⏰ Refusing to resume stale transaction` in backend logs is a signal that the primary disconnect handler chain failed for that session — investigate the disconnect handler error logs around the same charger ID.

#### Zero-Energy Watchdog (`backend/services/zero_energy_watchdog.py`)
**Purpose**: Auto-stop charging sessions where energy register has stalled. Detects vehicle BMS issues, charger meter regressions, and stuck handshakes.

**Operation**:
- Hooked into `MeterValues` handler
- Tracks per-transaction state in Redis (`zero_energy:{txn_id}`)
- Skips check during initial grace period (`ZERO_ENERGY_GRACE_PERIOD_SECONDS`, default 60s)
- If energy hasn't advanced for `ZERO_ENERGY_TIMEOUT_SECONDS` (default 7200s / 2h, bumped 2026-05-21 from 120s), schedules `RemoteStopTransaction`
- **W5 hook**: when energy advances, also pops `disconnect_handler._disconnect_reset_count` for the transaction (zeros the flap counter)

**Rationale for 2-hour window** (2026-05-21): the previous 120s timeout was killing sessions whose EV had taper-completed (SOC cap reached, BMS pause) only a couple of minutes earlier. Operators wanted EVs to be able to sit idle on the connector for up to 2 hours before being auto-stopped — covers natural taper-end without leaving infinitely-stuck sessions. Customers paying via QR see their refund window extend from ~3 min after taper-end to ~2 hr after taper-end; flag this in customer-comms if relevant.

**Cleanup**: `clear_zero_energy_tracking(transaction_id)` is called from `transaction_finalizer.finalize_stopped_transaction`, ensuring state is removed on every stop path.

**Redis TTL invariant**: `set_zero_energy_state` uses `ttl=14400` (4h). This MUST remain strictly greater than `ZERO_ENERGY_TIMEOUT_SECONDS`, otherwise a charger that goes silent mid-stall lets the Redis state expire and resets the stall clock on reconnect — the watchdog would never trip. If you raise the timeout, raise the TTL too.

#### Operational Runbooks (`docs/runbooks/`)
**Purpose**: Single source of truth for on-call triage. Each runbook is linked from a New Relic alert condition via `runbook_url`, so the on-call engineer gets a one-click path from page → triage steps.

**Runbooks**:
- `stale-suspended-transactions.md` — `OCPPStaleSuspendedSwept` event at startup
- `disconnect-stop-spike.md` — surge in `OCPPDisconnectStopped` events
- `zero-energy-stop-spike.md` — surge in `OCPPZeroEnergyStopped` events

All runbooks follow the same H2 structure (Symptom / What it means / When it's normal / Triage / Mitigation / What NOT to do / Customer impact / Escalation / Related). Triage steps are copy-pasteable docker/psql/NRQL commands tailored to the EC2 + Docker Compose deployment.

### Infrastructure Components

#### Redis Manager (`backend/redis_manager.py`)
**Purpose**: Real-time connection state management + QR session caching

**Features**:
- **Connection Tracking**: Add/remove chargers from active connection registry
- **Bulk Status Queries**: Efficient dashboard status checking
- **Graceful Degradation**: Fallback mode when Redis unavailable
- **Automatic Cleanup**: Connection state cleanup on disconnect
- **QR Session Caching**: `set_qr_session()`, `get_qr_session()`, `delete_qr_session()` for budget enforcement during MeterValues
- **Cache Fallback**: If Redis miss on QR session, rebuilds from DB (Tortoise query)

#### Database Configuration (`backend/tortoise_config.py`)
**Purpose**: Environment-aware database configuration

**Features**:
- SSL configuration for production PostgreSQL
- Connection pooling optimization
- Migration management with Aerich

#### Authentication Middleware (`backend/auth_middleware.py`)
**Purpose**: Clerk JWT validation and role-based access control

**Features**:
- JWT token validation with Clerk
- Role-based endpoint protection
- User context injection for request handlers

---

## Frontend Components

### Application Architecture
**Framework**: Next.js 15.3.4 with App Router and React 19
**Pattern**: Server-first architecture with client components where needed

### Directory Structure (`frontend/`)
```
frontend/
├── app/                    # Next.js App Router pages
│   ├── layout.tsx         # Root layout with providers
│   ├── page.tsx           # Role-based dashboard
│   ├── auth/              # Authentication pages
│   ├── admin/             # Admin-only pages
│   │   ├── chargers/      # Charger management
│   │   ├── stations/      # Station management
│   │   ├── firmware/      # Firmware OTA management
│   │   ├── qr-codes/      # **NEW** QR code management for appless charging
│   │   │   ├── page.tsx   # QR code list with create/close actions
│   │   │   └── [id]/page.tsx  # QR detail with payment history & stats
│   │   └── users/         # User management
│   │       └── [id]/      # User detail pages
│   │           ├── page.tsx            # User profile
│   │           ├── transactions/       # Charging transactions
│   │           └── wallet/             # Wallet history
│   ├── stations/          # Station finder and maps
│   ├── scanner/           # QR code scanning
│   ├── my-sessions/       # **NEW** User's sessions & wallet
│   ├── my-charges/        # Public charger map + QR transaction history (no auth)
│   └── charge/            # Individual charger pages
├── components/            # Reusable React components
│   ├── ui/               # Shadcn/ui components
│   ├── Navbar.tsx        # Navigation with RBAC
│   ├── RoleWrapper.tsx   # Role-based component wrapper
│   └── QRScanner.tsx     # QR code scanning component
├── contexts/             # React context providers
│   ├── ThemeContext.tsx  # Theme management
│   └── QueryClientProvider.tsx # TanStack Query setup
├── contexts/             # React context providers
│   ├── AuthContext.tsx   # Clerk auth wrapper with global token access
│   ├── QueryClientProvider.tsx # TanStack Query setup
│   └── ThemeContext.tsx  # Light/dark/system theme management
├── lib/                  # API integration and utilities
│   ├── api-client.ts     # Base HTTP client with Clerk auth + New Relic instrumentation
│   ├── api-services.ts   # Domain-specific API services (19+ service objects)
│   ├── csv-export.ts     # CSV export utility for transaction data
│   ├── newrelic-browser.ts # New Relic browser agent config
│   ├── utils.ts          # Utility functions
│   └── queries/          # TanStack Query hooks
│       ├── chargers.ts   # Charger CRUD, OCPP commands, signal quality, errors
│       ├── dashboard.ts  # Dashboard stats and refresh
│       ├── firmware.ts   # Firmware upload, updates, status
│       ├── logs.ts       # Charger logs, timeline, audit logs
│       ├── public-stations.ts # Public station discovery (unauthenticated)
│       ├── qr-codes.ts   # QR code CRUD, payments
│       ├── stations.ts   # Station CRUD
│       ├── transactions.ts # Transaction details, meter values
│       └── users.ts      # User CRUD, transactions, wallet
└── types/                # TypeScript type definitions
    └── api.ts            # API response types
```

### Key Pages and Components

#### Role-Based Dashboard (`app/page.tsx`)
**Purpose**: Adaptive dashboard based on user role

**User Features**:
- Quick access to station finder and QR scanner
- Recent charging session history
- Wallet balance and transaction summary

**Admin Features**:
- Real-time system statistics and alerts
- Quick links to management interfaces
- Connection status monitoring

#### Station Management

##### Station Finder (`app/stations/page.tsx`)
**Purpose**: Interactive map-based station discovery
**Features**:
- React Leaflet integration for interactive mapping
- Real-time station availability status
- Distance-based sorting and filtering
- Mobile-responsive design

##### Station Map Component (`components/StationMap.tsx`)
**Purpose**: Shared interactive Leaflet map with station markers (moved from `app/stations/`)
**Used by**: `/stations` page (authenticated) and `/my-charges` page (public)
**Features**:
- Color-coded markers: green (available), yellow (all busy), red (offline)
- User location with pulsing blue dot
- Popup with station name, address, availability, price, connectors
- Exports `StationWithDistance` interface for consumers

#### Admin Management Interface

##### Charger Management (`app/admin/chargers/page.tsx`)
**Purpose**: Comprehensive OCPP charger management

**OCPP Features**:
- Real-time charger status with color-coded indicators
- Connection monitoring with heartbeat status
- Remote OCPP commands (Start/Stop, ChangeAvailability)
- Bulk operations for multi-charger management

##### Charger Detail (`app/admin/chargers/[id]/page.tsx`)
**Purpose**: Individual charger monitoring and control

**OCPP Capabilities**:
- Live charger state updates
- OCPP remote commands with immediate feedback
- Real-time meter values (energy, power, current, voltage)
- Complete transaction history with energy consumption charts

##### User Management (`app/admin/users/[id]/page.tsx`)
**Purpose**: Comprehensive user account management
**Features**:
- User profile and role management
- Transaction history with energy consumption analysis
- Wallet balance and transaction management
- Admin override capabilities

##### **NEW**: User Transaction Pages (`app/admin/users/[id]/transactions/page.tsx`)
**Purpose**: View all charging transactions for a specific user
**Features**:
- Paginated list of all user charging sessions
- Transaction status badges (Completed, Failed, Running, Billing Failed)
- Energy consumption and duration display
- Start/end timestamps
- Links to detailed transaction view
- Filter and search capabilities

##### **NEW**: User Wallet History (`app/admin/users/[id]/wallet/page.tsx`)
**Purpose**: Complete wallet transaction history for a user
**Features**:
- All wallet transactions (TOP_UP and CHARGE_DEDUCT)
- **Running balance calculation** - Shows balance after each transaction
- Type-based color coding (green for credit, red for debit)
- Payment metadata display
- Pagination (15 transactions per page)
- Transaction descriptions and timestamps

#### User Experience Features

##### QR Code Scanner (`app/scanner/page.tsx`)
**Purpose**: Quick charger access via QR code scanning
**Technology**: ZXing library for barcode/QR code recognition
**Features**:
- Camera-based QR code detection
- Direct navigation to charger interface
- Error handling for invalid codes

##### Charger Interface (`app/charge/[id]/page.tsx`)
**Purpose**: User-friendly charger interaction
**Features**:
- Real-time charger status display
- Remote start/stop capabilities (if authorized)
- Live energy consumption monitoring
- Session progress tracking

##### **NEW**: My Sessions Page (`app/my-sessions/page.tsx`)
**Purpose**: Combined view of user's charging and wallet activity
**Features**:
- Current wallet balance display with auto-refresh
- **NEW**: Wallet recharge button with Razorpay integration
- Dual-tab or unified timeline view:
  - **Charging Sessions**: All charging transactions with duration, energy, and charger info
  - **Wallet Transactions**: All wallet activity with amounts and descriptions
- Real-time balance updates (30-second refresh interval)
- Transaction status indicators
- Mobile-responsive design
- Quick access to transaction details

##### **NEW**: Wallet Recharge Modal (`components/WalletRechargeModal.tsx`)
**Purpose**: Secure wallet recharge interface with Razorpay payment integration
**Technology**: Razorpay Checkout.js loaded dynamically from CDN

**Features**:
- Amount input with validation (₹1 - ₹1,00,000)
- Quick amount buttons (₹100, ₹200, ₹500, ₹1000)
- Real-time amount validation (decimal support, positive values only)
- Razorpay Checkout modal integration
- Payment status feedback with toast notifications
- Automatic wallet balance refresh on success
- Loading states during payment processing
- Error handling for failed payments

**Payment Flow**:
```typescript
1. User enters amount → Validation
2. Click "Recharge" → Create order on backend
3. Load Razorpay script (if not loaded)
4. Open Razorpay Checkout modal
5. User completes payment → Razorpay callback
6. Verify payment on backend → Update wallet
7. Show success toast → Refresh balance
```

**Security**:
- Order creation on secure backend
- Payment signature verification
- Webhook backup for reliability
- No payment credentials stored on frontend

**User Experience**:
- Seamless payment modal integration
- Instant balance updates on success
- Clear error messages on failure
- Mobile-responsive design
- Accessibility features (keyboard navigation, ARIA labels)

### State Management & Data Flow

#### TanStack Query Integration (`lib/queries/`)
**Pattern**: Domain-specific query hooks for all data operations

**Query Categories**:
- `stations.ts`: Station CRUD operations and geographic queries
- `chargers.ts`: Charger management, OCPP commands, real-time status
- `users.ts`: User management and profile operations
- `transactions.ts`: Transaction tracking and meter value aggregation
- `dashboard.ts`: System statistics and overview data

**Features**:
- **Optimized Caching**: Resource-specific stale times (stations: 2min, chargers: 10s)
- **Auto-refresh**: Real-time updates for dynamic data
- **Optimistic Updates**: Immediate UI feedback with rollback capability
- **Error Boundaries**: Comprehensive error handling with user feedback

#### API Integration Layer (`lib/`)

##### API Client (`lib/api-client.ts`)
**Purpose**: Base HTTP client with Clerk authentication integration
**Features**:
- Automatic JWT token injection from Clerk session
- Standardized error handling with user-friendly messages
- Request/response logging for debugging

##### API Services (`lib/api-services.ts`)
**Purpose**: Domain-specific service layer with typed responses
**Services**:
- `stationService`: Station CRUD with geographic operations
- `chargerService`: Charger management with OCPP command integration
- `userService`: User management and profile operations
- `transactionService`: Transaction tracking and reporting

### Authentication & Role Management

#### Middleware (`middleware.ts`)
**Purpose**: Route-level authentication and role-based access control
**Features**:
- JWT validation for protected routes
- Role-based redirects (USER vs ADMIN)
- Session management and token refresh

#### Role Wrapper Component (`components/RoleWrapper.tsx`)
**Purpose**: Component-level RBAC implementation
**Components**:
- `AuthenticatedOnly`: Requires any authenticated user
- `AdminOnly`: Requires ADMIN role
- `UserOnly`: Requires USER role
- `RoleBasedContent`: Conditional rendering based on role

---

## Mobile App Components

### Overview
The mobile app (`/app/`) is a **complete native iOS and Android application** built with Capacitor 7.4.4, wrapping a React web app to provide native mobile experiences. It represents a parallel user-facing application alongside the web frontend, optimized specifically for mobile users with native device features.

**Key Characteristics**:
- **Framework**: Capacitor (web-to-native wrapper) + React 19 + Vite 7.2.4
- **Platform Support**: iOS and Android with native builds
- **Feature Complete**: 100% complete according to IMPLEMENTATION_STATUS.md
- **Deployment Ready**: Configured for App Store and Google Play submission
- **Code Size**: ~3K lines of source code + comprehensive component library
- **App ID**: `com.lyncpower.user`

### Mobile App Architecture

```
┌────────────────────────────────────────────────────────┐
│                 Mobile App (Capacitor)                 │
│                                                        │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐ │
│  │   React UI   │  │  Capacitor   │  │   Native    │ │
│  │  Components  │◄─┤   Plugins    │◄─┤  iOS/Android│ │
│  │  (TSX/TS)    │  │  (Bridge)    │  │   Features  │ │
│  └──────────────┘  └──────────────┘  └─────────────┘ │
│         │                  │                  │        │
│         └─────── HTTP API ─┴──────────────────┘       │
└────────────────────────────│───────────────────────────┘
                             │
                             ▼
                    Backend FastAPI Server
```

### Directory Structure (`/app/`)

```
app/
├── src/                          # React application source
│   ├── screens/                  # 6 main screens
│   │   ├── HomeScreen.tsx        # Welcome + quick actions
│   │   ├── StationsScreen.tsx    # Interactive map
│   │   ├── ScannerScreen.tsx     # QR code scanner
│   │   ├── ChargeScreen.tsx      # Live charging session
│   │   ├── SessionsScreen.tsx    # Transaction history
│   │   └── SignInScreen.tsx      # Authentication
│   ├── components/               # Reusable components
│   │   ├── ErrorBoundary.tsx     # Error handling
│   │   ├── Layout.tsx            # Bottom navigation
│   │   ├── Modal.tsx             # Mobile modal
│   │   ├── NetworkStatus.tsx     # Connectivity indicator
│   │   ├── PullToRefresh.tsx     # Gesture handler
│   │   └── *Skeleton.tsx         # Loading states
│   ├── hooks/                    # Custom React hooks
│   │   ├── useNetworkStatus.ts   # Network detection
│   │   ├── usePullToRefresh.ts   # Pull-to-refresh
│   │   └── useStatusBar.ts       # Status bar control
│   ├── lib/                      # API integration
│   │   ├── api-client.ts         # HTTP client
│   │   └── api-services.ts       # User API methods
│   ├── routes.tsx                # React Router setup
│   └── App.tsx                   # App entry point
├── android/                      # Native Android project
│   ├── app/                      # Android app module
│   │   ├── src/main/AndroidManifest.xml  # Permissions
│   │   └── build.gradle          # Android build config
│   └── gradle/                   # Gradle wrapper
├── ios/                          # Native iOS project
│   └── App/                      # iOS app module
│       ├── App/Info.plist        # iOS permissions
│       └── App.xcodeproj/        # Xcode project
├── capacitor.config.ts           # Capacitor configuration
├── vite.config.ts                # Vite build configuration
├── package.json                  # Dependencies
├── IMPLEMENTATION_STATUS.md      # Feature completion tracking
└── README.md                     # Setup instructions
```

### Application Entry Point

#### Main Application (`src/App.tsx`)
**Purpose**: Capacitor app root with providers and routing
**Key Features**:
- Clerk authentication provider setup
- TanStack Query client configuration
- Error boundary wrapping
- React Router integration
- Status bar initialization

```typescript
function App() {
  return (
    <ClerkProvider publishableKey={clerkKey}>
      <QueryClientProvider client={queryClient}>
        <ErrorBoundary>
          <RouterProvider router={router} />
        </ErrorBoundary>
      </QueryClientProvider>
    </ClerkProvider>
  );
}
```

### Screen Components

#### 1. Home Screen (`screens/HomeScreen.tsx`)
**Purpose**: Welcome screen with quick access to main features
**Features**:
- Welcome message with user greeting
- Quick action buttons (Find Stations, Scan QR)
- "How to Charge" instructions section
- Visual guides for first-time users

#### 2. Stations Screen (`screens/StationsScreen.tsx`)
**Purpose**: Interactive map for discovering charging stations
**Features**:
- **Leaflet Map Integration**: Full-screen interactive map
- **Geolocation**: User's current location with distance calculation (Haversine formula)
- **Color-Coded Markers**: Green (available chargers), Red (all busy)
- **Station Details**: Bottom sheet with:
  - Station name and address
  - Distance from user
  - Available/total chargers count
  - "Get Directions" button (opens Google Maps)
- **Real-time Data**: Auto-refresh station availability
- **Pull-to-Refresh**: Manual refresh gesture

#### 3. Scanner Screen (`screens/ScannerScreen.tsx`)
**Purpose**: QR code scanning for charger access
**Native Plugin**: `@capacitor/barcode-scanner` v2.2.0
**Features**:
- Camera permission handling
- QR code and barcode scanning
- Manual alphanumeric input fallback
- Automatic navigation to charge screen on success
- Error handling for denied permissions

#### 4. Charge Screen (`screens/ChargeScreen.tsx`)
**Purpose**: Live charging session monitoring and control
**Features**:
- **Real-time Status**: Updates every 2-3 seconds
- **Live Meter Values**:
  - Energy consumed (kWh)
  - Current power (kW)
  - Voltage (V)
  - Current (A)
- **Session Controls**:
  - Remote start/stop charging buttons
  - Session duration timer
  - Estimated cost calculation
- **Status Indicators**: Visual charger status (Available, Charging, Faulted, etc.)
- **Auto-refresh**: Continuous polling for live data

#### 5. Sessions Screen (`screens/SessionsScreen.tsx`)
**Purpose**: Combined transaction history and wallet management
**Features**:
- **Merged History**: Charging sessions + wallet transactions
- **Wallet Balance**: Prominent display with recharge button
- **Razorpay Integration**: Native payment modal for recharge
- **Transaction Details**:
  - Date, time, and amount
  - Transaction type (charge/topup)
  - Status indicators
- **Pull-to-Refresh**: Manual data refresh
- **Pagination**: Load more on scroll

#### 6. Sign In Screen (`screens/SignInScreen.tsx`)
**Purpose**: User authentication via Clerk
**Features**:
- Clerk sign-in component integration
- Automatic redirect on success
- Error handling
- Mobile-optimized layout

### Mobile-Specific Components

#### Layout Component (`components/Layout.tsx`)
**Purpose**: Main app layout with bottom navigation
**Features**:
- **Bottom Tab Navigation**: 5 tabs (Home, Stations, Scan, Sessions, Profile)
- **Header**: App logo + user info
- **Responsive**: Adapts to different screen sizes
- **Active Tab Highlighting**: Visual feedback

#### Error Boundary (`components/ErrorBoundary.tsx`)
**Purpose**: Comprehensive error handling for mobile
**Features**:
- Catches React errors
- User-friendly error messages
- Reload button
- Error logging (for debugging)

#### Network Status (`components/NetworkStatus.tsx`)
**Purpose**: Network connectivity indicator
**Features**:
- Real-time network status via Capacitor Network plugin
- Visual banner when offline
- Auto-hide when online

#### Pull-to-Refresh (`components/PullToRefresh.tsx`)
**Purpose**: Standard mobile gesture for data refresh
**Features**:
- Touch gesture detection
- Visual loading indicator
- Callback function on complete
- Configurable refresh threshold

### Native Integrations

#### Capacitor Plugins
The app uses 4 official Capacitor plugins for native features:

1. **Barcode Scanner** (`@capacitor/barcode-scanner` v2.2.0)
   - QR code and barcode scanning
   - Camera permission handling
   - Supports all standard barcode formats

2. **Geolocation** (`@capacitor/geolocation` v7.1.5)
   - GPS location access
   - Distance calculations
   - Location permission handling
   - Background location support

3. **Network** (`@capacitor/network` v7.0.2)
   - Network connectivity status
   - WiFi/Cellular detection
   - Real-time connectivity events

4. **Razorpay** (`capacitor-razorpay` v1.3.0)
   - Native payment SDK integration
   - Secure payment flow
   - iOS and Android support
   - Test/Live mode switching

#### Platform-Specific Configuration

**iOS Configuration** (`ios/App/App/Info.plist`):
```xml
<key>NSCameraUsageDescription</key>
<string>Camera access is required to scan QR codes on chargers</string>

<key>NSLocationWhenInUseUsageDescription</key>
<string>Location access helps find nearby charging stations</string>
```

**Android Configuration** (`android/app/src/main/AndroidManifest.xml`):
```xml
<uses-permission android:name="android.permission.CAMERA" />
<uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" />
<uses-permission android:name="android.permission.ACCESS_COARSE_LOCATION" />
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />
```

### API Integration

#### API Client (`src/lib/api-client.ts`)
**Purpose**: Centralized HTTP client with Clerk JWT integration
**Features**:
- Automatic JWT token injection
- Request/response interceptors
- Error handling
- Base URL configuration

#### API Services (`src/lib/api-services.ts`)
**Purpose**: User-focused API method wrappers
**Services**:
- `stationsService`: Get stations, charger details
- `chargingService`: Remote start/stop, session monitoring
- `sessionsService`: Transaction history
- `walletService`: Wallet balance, recharge, history

### Custom Hooks

#### Network Status Hook (`hooks/useNetworkStatus.ts`)
```typescript
const { isConnected, connectionType } = useNetworkStatus();
```
**Features**:
- Real-time network status
- WiFi/Cellular detection
- React state updates

#### Pull-to-Refresh Hook (`hooks/usePullToRefresh.ts`)
```typescript
const { refreshing, onRefresh } = usePullToRefresh(async () => {
  await refetchData();
});
```
**Features**:
- Gesture handling
- Loading state management
- Async callback support

#### Status Bar Hook (`hooks/useStatusBar.ts`)
```typescript
useStatusBar({ style: 'dark' });
```
**Features**:
- Status bar style control
- iOS and Android support
- Automatic cleanup

### Build and Deployment

#### Development Build
```bash
cd app
npm install
npm run dev  # Vite dev server on http://localhost:5173
```

#### Native Builds
```bash
# iOS
npm run build
npx cap sync ios
npx cap open ios  # Open in Xcode

# Android
npm run build
npx cap sync android
npx cap open android  # Open in Android Studio
```

#### Production Configuration
- **App ID**: `com.lyncpower.user` (configured in capacitor.config.ts)
- **Bundle ID**: Same as App ID for iOS
- **Package Name**: Same as App ID for Android
- **App Name**: "LyncPower"
- **Estimated Store Submission Time**: 4-7 hours (after developer account setup)

### Mobile App Features Summary

| Feature | Status | Implementation |
|---------|--------|----------------|
| Authentication | ✅ Complete | Clerk React SDK |
| Station Finder | ✅ Complete | Leaflet + Geolocation |
| QR Scanner | ✅ Complete | Capacitor Barcode Scanner |
| Live Charging | ✅ Complete | Real-time polling + WebSocket fallback |
| Remote Control | ✅ Complete | Start/Stop via API |
| Transaction History | ✅ Complete | Merged charging + wallet |
| Wallet Recharge | ✅ Complete | Razorpay native SDK |
| Pull-to-Refresh | ✅ Complete | Custom gesture handling |
| Network Status | ✅ Complete | Capacitor Network plugin |
| Error Handling | ✅ Complete | Error boundary + logging |
| Loading States | ✅ Complete | Skeleton components |
| Push Notifications | ❌ NOT Implemented | Proposed but missing |
| Offline Mode | ❌ NOT Implemented | Future enhancement |
| Biometrics | ❌ NOT Implemented | Future enhancement |

### Key Differences from Web Frontend

| Aspect | Web Frontend | Mobile App |
|--------|-------------|------------|
| **Users** | Admins + Users | Users only |
| **Features** | Admin dashboard + user UI | User features only |
| **Navigation** | Top navbar + sidebar | Bottom tabs |
| **Map Library** | Same (React Leaflet) | Same (React Leaflet) |
| **Build Tool** | Next.js | Vite |
| **Native Features** | None | QR, GPS, Payments, Network |
| **Deployment** | Vercel | App Stores |
| **Framework** | Next.js 15 App Router | React 19 + React Router |
| **Bundle Size** | ~2MB (includes admin) | ~500KB (user only) |

---

## QR-Based Appless Charging

### Overview
The QR-based appless charging feature enables customers to charge their EV by scanning a Razorpay UPI QR code at the charger and paying any amount via their UPI app (Google Pay, PhonePe, etc.) — **without needing to download an app or create an account**. The system automatically starts charging, enforces a budget limit, and refunds any unused balance after the session.

### Payment Safety Guarantees

- **Atomic refund idempotency** — `QRPaymentService._full_refund` wraps its check-decide-write flow in `async with in_transaction()` and uses `QRPayment.select_for_update().get(id=...)` so concurrent callers (webhook retries, watchdog, billing) serialize on the row. Exactly one refund is issued.
- **Concurrent-payment rejection** — `handle_qr_payment` wraps the active-transaction + pending-QR check in a transaction with `Charger.select_for_update().get(id=charger.id)`. If the charger is busy, the new payment is created with `FAILED` status and auto-refunded outside the lock; the charger holder is unaffected.
- **Razorpay "already refunded" reconciliation** — When Razorpay returns a fully-refunded error, `razorpay_service` raises `RazorpayAlreadyRefundedError`. `_full_refund` catches it, calls `find_refund_for_payment()`, persists the pre-existing refund ID, and logs `refund_reconciled=true`. The database row ends consistent with Razorpay's state.
- **Indexed order-id lookup** — `WalletTransaction.razorpay_order_id` is a dedicated indexed column (migration 14). Webhook handlers use a direct indexed lookup instead of scanning the 1000 most recent rows (old JSON fallback retained for pre-migration rows only).
- **Rate-limit Redis keys are `ratelimit:public_qr_transactions:{ip}`** (the `ratelimit:` prefix is added by `RedisConnectionManager.rate_limit_check`, not by callers). Test conftest function-scoped autouse fixture flushes `ratelimit:public_qr_transactions:*` before every test so cumulative request counts across the suite don't trip the 20-req/60s public-endpoint limiter.
- **Non-negative `wallet_transaction.amount`** — `WalletTransaction.save()` raises `ValueError` if `amount < 0`, and migration 32 added a Postgres CHECK constraint `wallet_transaction_amount_non_negative (amount >= 0) NOT VALID`. Migration 33 backfilled `ABS(amount)` on legacy negative CHARGE_DEDUCT rows and redeemed the constraint to `VALID`. Convention: `amount` is always non-negative; direction is carried entirely by `type` (`TOP_UP` credits, `CHARGE_DEDUCT` debits). Frontend wallet-history views (`admin/chargers/[id]/page.tsx`) render direction from `type`, not from amount sign.

- **Wallet session budget cap + RemoteStop auto-stop (Module B).** Wallet-paid charging sessions enforce the same kind of in-session budget cap as QR sessions. On StartTransaction the wallet's available balance is snapshotted into Redis as `wallet_session:{transaction_id}` (paise-int, 24 h TTL, payload includes `tariff_rate`, `gst_percent`, `start_meter_kwh`, `auto_stop_scheduled`). On every MeterValues frame, `WalletSessionService.check_balance_and_auto_stop` (`backend/services/wallet_session_service.py`) recomputes the accumulated cost `(reading_kwh − start_meter_kwh) × rate × (1 + gst%)` and compares it to the snapshot. When `cost ≥ budget_limit`, it schedules `RemoteStopTransaction` via `safe_create_task` — never awaits, because the MeterValues handler has not yet sent its CALLRESULT and awaiting an outbound CALL would deadlock the OCPP session. The `auto_stop_scheduled` flag in the payload, set *before* dispatch, makes late MeterValues frames in the same window no-ops so a charger that sends rapid-fire frames doesn't fire a second stop. After a server restart the Redis cache is empty; `_rebuild_session_from_db` reconstructs the payload by reading the live wallet balance via `WalletService.get_balance` and re-writing the cache, so restarts mid-session don't forfeit the cap. The cache key is deleted on StopTransaction. QR sessions are filtered out of the rebuild path (they're driven by their own QR budget cache); the two systems coexist cleanly side-by-side at `main.py:1108-1140`.

- **Wallet balance is derived from the log (Module C, migration 33).** The `wallet.balance` column was dropped. Balance is now `SUM(amount)` over `wallet_transaction` rows where `type = 'TOP_UP' AND payment_metadata->>'status' = 'COMPLETED'` minus `SUM(amount)` over `type = 'CHARGE_DEDUCT'` rows — a single-table aggregate served by `WalletService.get_balance(wallet_id)` (`backend/services/wallet_service.py`). PENDING and FAILED top-ups are filtered out by design so unconfirmed Razorpay orders never credit the wallet. The hot read path (`/users/me`, admin user list, recharge endpoints) is fronted by a Redis cache (`wallet_balance:{wallet_id}`, paise-int, 1 h TTL) invalidated by `WalletService._invalidate_balance_cache` on every successful billing or top-up (invalidation runs **after** the outer `@atomic()` commits, so concurrent readers can't repopulate the cache with pre-commit data). The index `idx_wallet_txn_balance (wallet_id)` keeps the aggregate cheap — measured 0.18ms at N=200, 0.97ms at N=5000. **Migration 33 captured pre-existing stored-vs-derived drift as auto-generated adjustment rows** (description "Pre-ledger-migration drift correction (auto-generated by migration 33)") so derived balance post-migration matches each wallet's stored balance at migration time. The `wallet` row still exists to anchor FKs and serve as the row-level lock target for serialising concurrent top-ups / charges on the same user. To audit drift after the fact, `backend/scripts/reconcile_wallet_balance.py` reads the live ledger and prints discrepancies.

#### Wallet migration rollback runbook (32 / 33 / 34)

**Important caveat:** Aerich's `aerich` tracking table can lag behind the filesystem migration list — `aerich downgrade` operates on its tracked version and may try to roll back unrelated earlier migrations (e.g. `gst_invoice`) and fail with `DependentObjectsStillExistError`. **Do not rely on `aerich downgrade` for production rollback of migrations 32–34.** Run the SQL by hand instead. Verified the down/up cycle works for migration 34 in dev.

**Pre-flight:** take a logical backup of the `wallet`, `wallet_transaction`, and `aerich` tables before any rollback. `pg_dump` filtered to those tables is sufficient — the wallet domain is the entire scope of these migrations.

**To roll back migration 34** (the index tightening):
```sql
DROP INDEX IF EXISTS "idx_wallet_txn_balance";
CREATE INDEX IF NOT EXISTS "idx_wallet_txn_balance"
    ON "wallet_transaction" (wallet_id) INCLUDE (amount, type);
```
Safe under live traffic — the index is rebuilt while the old one is dropped. Brief lock during DROP.

**To roll back migration 33** (the ledger migration — destructive of the new ledger model):
```sql
-- Re-add the column with derived values so the old code can boot.
ALTER TABLE "wallet" ADD COLUMN "balance" DECIMAL(10,2);

UPDATE "wallet" w
   SET balance = COALESCE((
       SELECT SUM(CASE
                  WHEN type = 'TOP_UP'
                       AND payment_metadata->>'status' = 'COMPLETED'
                       THEN amount
                  WHEN type = 'CHARGE_DEDUCT'
                       THEN -amount
                  ELSE 0
              END)
         FROM "wallet_transaction"
        WHERE wallet_id = w.id
   ), 0);

-- Drop the covering index and roll the CHECK back to NOT VALID.
DROP INDEX IF EXISTS "idx_wallet_txn_balance";
ALTER TABLE "wallet_transaction"
  DROP CONSTRAINT IF EXISTS "wallet_transaction_amount_non_negative";
ALTER TABLE "wallet_transaction"
  ADD CONSTRAINT "wallet_transaction_amount_non_negative"
  CHECK (amount >= 0) NOT VALID;
```
**Caveat 1:** the drift-correction adjustment rows inserted by 33's auto-heal remain in `wallet_transaction` (description `'Pre-ledger-migration drift correction...'`). They are harmless but visible in the wallet history UI. Delete them if you need a clean rollback: `DELETE FROM wallet_transaction WHERE description LIKE 'Pre-ledger-migration drift correction%';`. **Caveat 2:** the sign-normalisation `UPDATE ... SET amount = ABS(amount)` is irreversible without a backup — the original negative signs are lost. **For full rollback, restore from the pre-migration `pg_dump` instead.**

**To roll back migration 32** (the CHECK constraint):
```sql
ALTER TABLE "wallet_transaction"
  DROP CONSTRAINT IF EXISTS "wallet_transaction_amount_non_negative";
```
Always safe.

**Post-rollback verification:**
1. `\d+ wallet` shows `balance` column present.
2. `\d+ wallet_transaction` shows expected constraint state.
3. `python -m scripts.reconcile_wallet_balance` exits zero with drift = 0 across all wallets (because step 33's UPDATE built `balance` from the same formula `get_balance` would use).
4. Deploy the old code; smoke-test wallet recharge + charge.

**Aerich reconciliation:** if you also want `aerich` state to reflect the rollback, manually `DELETE FROM aerich WHERE version IN (...)` the relevant rows. Skipping this is fine for emergency rollback — the next deploy can re-sync.

#### Wallet drift alerting

The reconciliation script (`backend/scripts/reconcile_wallet_balance.py`) is read-only, exits zero on no drift and non-zero on drift above the threshold. Recommended deployment as a daily cron on both staging and prod:

```cron
# Nightly wallet ledger reconciliation @ 02:30 IST
30 2 * * *  docker exec ocpp-backend python -m scripts.reconcile_wallet_balance --threshold 1.00 >> /var/log/voltlync/reconcile.log 2>&1
```

For AWS-managed staging/prod, the equivalent remote invocation (matches the project's standard `voltlync` profile pattern documented elsewhere in this doc):

```bash
aws ssm send-command \
  --profile voltlync \
  --instance-ids <ec2-id-from-Makefile> \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["docker exec ocpp-backend python -m scripts.reconcile_wallet_balance --threshold 1.00"]'
```

**Alert wiring:** the script exits non-zero when any wallet's drift exceeds the threshold. Wire that exit code into the existing monitoring path — Sentry (if the script's stderr is forwarded), or a CloudWatch alarm on the SSM command's `Status` field, or a Slack webhook from the cron wrapper. Drift > ₹1 should page on-call; drift > 0 but < ₹1 should ticket. The `Custom/Wallet/NegativeBalance` New Relic metric (emitted by `WalletService.get_balance` whenever a derived balance comes out negative) is the runtime-side complement to this batch check.
- **Webhook retries avoided** — All Razorpay webhook handlers return HTTP 200 on application errors (logged) so Razorpay does not retry. Only infrastructure failures (DB/Redis) surface as 5xx.
- **PII masked in logs** — `mask_vpa()`, `mask_phone()`, `mask_payment_id()`, `mask_email()` helpers in `utils.py` are applied in all QR payment log statements. Logs forwarded to New Relic contain only masked identifiers.

### Payment & Charging Flow

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Customer     │    │  Razorpay    │    │  Backend     │    │  Charger     │
│  (UPI App)    │    │  (Webhook)   │    │  (CSMS)      │    │  (OCPP 1.6)  │
└──────┬───────┘    └──────┬───────┘    └──────┬───────┘    └──────┬───────┘
       │ Scan QR & Pay ₹X  │                    │                    │
       │──────────────────►│                    │                    │
       │                    │ qr_code.credited   │                    │
       │                    │───────────────────►│                    │
       │                    │                    │ Resolve user       │
       │                    │                    │ (phone/VPA/guest)  │
       │                    │                    │                    │
       │                    │                    │ RemoteStartTxn     │
       │                    │                    │───────────────────►│
       │                    │                    │                    │
       │                    │                    │◄─ StartTransaction │
       │                    │                    │  Link QR payment   │
       │                    │                    │  Cache budget in   │
       │                    │                    │  Redis             │
       │                    │                    │                    │
       │                    │                    │◄─ MeterValues      │
       │                    │                    │  Check budget      │
       │                    │                    │  Auto-stop if      │
       │                    │                    │  exceeded          │
       │                    │                    │                    │
       │                    │                    │◄─ StopTransaction  │
       │                    │                    │  Calculate cost    │
       │                    │  Refund unused ₹   │  Issue refund      │
       │◄───────────────────│◄───────────────────│                    │
```

### Step-by-Step Implementation

#### Step 1: Admin Creates QR Code
- `POST /api/admin/qr-codes` with `charger_id`
- Backend calls `razorpay_service.create_qr_code()` → Razorpay returns `qr_code_id`, `image_url`, `short_url`
- QR code stored in `ChargerQRCode` table, printed/displayed at charger

#### Step 2: Customer Pays via UPI
- Customer scans QR with any UPI app (Google Pay, PhonePe, etc.)
- Enters amount (e.g., ₹500) and confirms payment
- Razorpay captures payment and sends `qr_code.credited` webhook

#### Step 3: Webhook Processing (Idempotent)
- `POST /webhooks/razorpay` receives webhook with HMAC-SHA256 signature verification
- **Idempotency check**: Skip if `razorpay_payment_id` already exists in `QRPayment` table
- **Staleness check**: Refund if payment is >5 minutes old (`QR_PAYMENT_PENDING_TIMEOUT`)
- **Double-payment guard**: Refund if charger already has active transaction or pending QR payment

#### Step 4: User Resolution (Priority-based)
1. **Phone match**: If customer phone matches existing user → use that user
2. **VPA match**: If customer UPI VPA matches existing user → use that user
3. **Create UPI_GUEST**: New user with email `upi_{vpa}@guest.powerlync.com`, auth_provider=`UPI_GUEST`
4. **System guest fallback**: `guest@system.powerlync.com` if no identifiers available

#### Step 5: Charging Trigger
- **If charger is PREPARING (or AVAILABLE for socket chargers) + connected**: Immediately send `RemoteStartTransaction`
- **If charger is connected but not in startable state**: Background task polls every 10s for 5 minutes (also accepts Available for socket chargers)
- **If charger is disconnected**: Full refund, status=FAILED
- **RemoteStart retry**: Up to 2 attempts with 5s delay; full refund if all fail

#### Step 6: Transaction Linking (`on_start_transaction`)
- When charger sends `StartTransaction`, backend calls `link_transaction_to_qr_payment()`
- Links `transaction_id` to `QRPayment`, sets status=CHARGING
- **Caches session in Redis** (`qr_session:{transaction_id}`) with budget_limit, tariff_rate, gst_percent, start_meter

#### Step 7: Budget Enforcement (`on_meter_values`)
- On each `MeterValues`, calls `check_budget_and_auto_stop()`
- Retrieves session from Redis (or rebuilds from DB on cache miss)
- Calculates: `cost = (reading_kwh - start_meter) × tariff_rate × (1 + gst_percent/100)` (cost now includes GST)
- **If cost >= budget_limit**: Schedules `RemoteStopTransaction` as `asyncio.create_task()` (non-blocking to avoid deadlock)

#### Step 8: Billing & Refund (`on_stop_transaction`)
- Calls `process_qr_session_billing(transaction_id)`
- Calculates: `energy_cost = energy_consumed × tariff_rate`
- Calculates: `gst_amount = energy_cost × gst_percent / 100` (GST on energy cost only)
- Computes `platform_fee = _synthetic_platform_fee(amount_paid)` (fixed 2%, ADR 0001). Also calls `_ensure_actual_fee_captured(qr_payment)` so the actual Razorpay fee lands on the row for ops/reconciliation.
- Calculates: `refund = amount_paid - energy_cost - gst_amount - synthetic_platform_fee`
- **If refund >= ₹1.0**: Issues partial refund via Razorpay, sets status=REFUNDED
- **If refund < ₹1.0**: Absorbed as operator credit, sets status=COMPLETED
- Deletes Redis session cache

### QR Payment Status Lifecycle
```
PAID → CHARGING → COMPLETED → REFUNDED
  ↓         ↓         ↑
FAILED   EXPIRED   (no refund needed, amount < ₹1)
  ↓
REFUND_FAILED
```

### Admin QR Management Pages

**QR Code List** (`/admin/qr-codes`):
- Table: Charger, Charge Point ID, QR Code ID, Status, Payments, Revenue, Created, Actions
- Filters: Search by charger name, Status (Active/Inactive/All)
- Actions: Create QR, View details, Close QR
- Create dialog: Select charger from dropdown

**QR Code Detail** (`/admin/qr-codes/[id]`):
- QR code image display with Download, Print, Close buttons
- Stats cards: Total Payments, Total Revenue, Total Refunds
- Payment history table: Date, Amount, Customer VPA, Energy Cost, Platform Fee, Refund, Status
- Color-coded status badges

### Configuration
| Variable | Default | Purpose |
|----------|---------|---------|
| `RAZORPAY_PLATFORM_FEE_PERCENT` | 2.0 | Authoritative synthetic platform-fee rate (%) used for budget cap, over-payment refund, and invoice gateway-charges line. ADR 0001. Startup fails loud if missing/zero. |
| `QR_PAYMENT_PENDING_TIMEOUT` | 300 | Seconds before a payment is considered stale |

### Test Script
```bash
# Simulate Razorpay webhook locally
docker compose exec backend python scripts/test_qr_webhook.py \
  --charger-id 10 --amount 500 --vpa testuser@okaxis --phone +919876543210

# Dry run (print payload + curl command)
docker compose exec backend python scripts/test_qr_webhook.py \
  --charger-id 10 --amount 500 --dry-run
```

---

## Database Schema

### Entity Relationship Overview

```
┌─────────────┐    ┌─────────────────┐    ┌─────────────┐
│    User     │◄──►│     Wallet      │◄──►│WalletTrans  │
│ (Clerk ID)  │    │                 │    │             │
│ (UPI_GUEST) │    └─────────────────┘    └─────────────┘
└─────┬───────┘                                   │
      │            ┌─────────────────┐           │
      ├───────────►│  Transaction    │◄──────────┘
      │            │ (OCPP Session)  │
      │            └─────┬───────────┘
      │                  │
      │   ┌──────────────┼──────────────────┐
      │   │              │                  │
      │ ┌─▼───────────┐ │ ┌────▼────┐ ┌────▼──────┐
      │ │MeterValue   │ │ │Charger  │ │Vehicle    │
      │ │(Energy Data)│ │ │(OCPP CP)│ │Profile    │
      │ └─────────────┘ │ └────┬────┘ └───────────┘
      │                  │      │
      │   ┌──────────────┘ ┌───▼─────┐
      │   │                │Station  │
      │   │                │(Location)│
      │   │                └─────────┘
      │   │
      │ ┌─▼──────────────┐    ┌─────────────────┐
      └►│  QRPayment     │◄──►│ ChargerQRCode   │
        │ (Appless Pay)  │    │ (Razorpay QR)   │
        └────────────────┘    └─────────────────┘
```

### Core Tables with File References

#### User Management Tables
```sql
-- User profiles integrated with Clerk (+ UPI_GUEST for appless users)
-- Defined in: backend/models.py:25-38
CREATE TABLE user (
    id SERIAL PRIMARY KEY,
    clerk_user_id VARCHAR(255) UNIQUE NOT NULL,  -- Clerk integration
    phone_number VARCHAR(20),
    full_name VARCHAR(255),
    email VARCHAR(255),
    rfid_card_id VARCHAR(255) UNIQUE,
    upi_vpa VARCHAR(255) UNIQUE,        -- NEW: UPI address for QR user lookup
    auth_provider VARCHAR(20),           -- NEW: EMAIL, GOOGLE, CLERK, UPI_GUEST
    role UserRoleEnum DEFAULT 'USER',  -- RBAC support
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Wallet system for billing
-- Defined in: backend/models.py:40-49
CREATE TABLE wallet (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES user(id) ON DELETE CASCADE,
    balance DECIMAL(10, 2) DEFAULT 0.00,
    currency VARCHAR(3) DEFAULT 'INR',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

#### Infrastructure Tables
```sql
-- Charging station locations
-- Defined in: backend/models.py:74-86
CREATE TABLE charging_station (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    latitude DECIMAL(10, 8),  -- Geographic coordinates
    longitude DECIMAL(11, 8),
    address TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- OCPP-compliant chargers
-- Defined in: backend/models.py:88-111
CREATE TABLE charger (
    id SERIAL PRIMARY KEY,
    charge_point_string_id VARCHAR(255) UNIQUE NOT NULL,  -- OCPP identifier
    station_id INTEGER REFERENCES charging_station(id),
    name VARCHAR(255),
    vendor VARCHAR(100),
    model VARCHAR(100),
    serial_number VARCHAR(100) UNIQUE,
    firmware_version VARCHAR(100),
    latest_status ChargerStatusEnum NOT NULL,  -- OCPP 1.6 statuses
    last_heart_beat_time TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Tariff configuration per charger
-- Defined in: backend/models.py (Tariff). ADR 0003 added the all-in column.
CREATE TABLE tariff (
    id SERIAL PRIMARY KEY,
    charger_id INTEGER REFERENCES charger(id),
    rate_per_kwh DECIMAL(8, 4) NOT NULL,                   -- INTERNAL back-derived rate (= all_in × 0.98 / 1.18); used by line-item billing math only, never customer-facing
    tariff_per_kwh_all_in DECIMAL(10, 4) NOT NULL,         -- OPERATOR-TYPED, CUSTOMER-DISPLAYED all-inclusive rate (incl. GST + synthetic 2% gateway fee). Authoritative for display
    gst_percent DECIMAL(5, 2) DEFAULT 18.00,               -- GST percentage; used in the back-derivation formula and at billing time
    hsn_sac_code VARCHAR(10),
    is_global BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
-- Admin-facing UX (post issue 04): the chargers admin UI takes the
-- *all-inclusive* per-kWh price (operator's intended customer-visible rate).
-- The API accepts ONLY `tariff_per_kwh_all_in` (validated 1.0–100.0); the
-- router back-derives `rate_per_kwh = all_in × (1 - fee_pct/100) / (1 + gst_percent/100)`
-- and persists both. The legacy `tariff_per_kwh` / `tariff_per_kwh_incl_tax`
-- request fields are rejected with 422 (`extra='forbid'`).
--
-- Migration 36 (2026-05-18) backfilled `tariff_per_kwh_all_in = rate × (1 + gst/100)`
-- and shrunk `rate_per_kwh *= 0.98` so the back-calc identity holds going
-- forward. Franchisees absorb a 2% margin on legacy tariffs until they
-- re-save via the new API; with two live chargers at cutover, ops handles
-- re-entry manually instead of via a banner endpoint. See ADR 0003.

-- Decimal precision convention (post migration 31):
--   Rate-like columns (per-kWh, per-unit prices): DECIMAL(8, 4)
--   Amount-like columns (line totals, GST amounts, ledger amounts): DECIMAL(*, 2) — paisa-precise to match Razorpay
--   Energy/kWh columns: DECIMAL(12, 3) — OCPP reports Wh resolution
--   Percentage rates (GST/commission/TDS): DECIMAL(5, 2) — statutory whole/half percentages
```

#### Firmware Management Tables
```sql
-- Firmware file metadata
-- Defined in: backend/models.py:292-309
CREATE TABLE firmware_file (
    id SERIAL PRIMARY KEY,
    version VARCHAR(50) UNIQUE NOT NULL,  -- Unique version identifier
    filename VARCHAR(255) NOT NULL,       -- Safe filename: {version}_{original}
    file_path VARCHAR(500) NOT NULL,      -- Absolute path on filesystem
    file_size BIGINT NOT NULL,            -- File size in bytes
    checksum VARCHAR(64) NOT NULL,        -- MD5 hash for integrity
    description TEXT,                     -- Release notes
    uploaded_by_id INTEGER REFERENCES app_user(id) ON DELETE CASCADE,
    is_active BOOLEAN DEFAULT TRUE,       -- Soft delete flag
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_firmware_file_version ON firmware_file(version);

-- Firmware update tracking per charger
-- Defined in: backend/models.py:311-326
CREATE TABLE firmware_update (
    id SERIAL PRIMARY KEY,
    charger_id INTEGER REFERENCES charger(id) ON DELETE CASCADE,
    firmware_file_id INTEGER REFERENCES firmware_file(id) ON DELETE CASCADE,
    status VARCHAR(19) NOT NULL DEFAULT 'PENDING',  -- FirmwareUpdateStatusEnum
    initiated_by_id INTEGER REFERENCES app_user(id) ON DELETE CASCADE,
    initiated_at TIMESTAMP DEFAULT NOW(),
    download_url TEXT NOT NULL,  -- Presigned S3 URL; TEXT because role-assumed STS tokens push URLs past 500 chars
    started_at TIMESTAMP,                -- When download began
    completed_at TIMESTAMP,              -- When update completed/failed
    error_message TEXT,                  -- Failure details
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_firmware_update_charger ON firmware_update(charger_id);
CREATE INDEX idx_firmware_update_status ON firmware_update(status);
```

**FirmwareUpdateStatusEnum Values**:
- `PENDING` - Update queued, awaiting OCPP command acknowledgment
- `DOWNLOADING` - Charger actively downloading firmware
- `DOWNLOADED` - Download complete, awaiting installation
- `INSTALLING` - Firmware installation in progress
- `INSTALLED` - Update successful (charger.firmware_version updated)
- `DOWNLOAD_FAILED` - Network/file download error
- `INSTALLATION_FAILED` - Installation or verification error
- `CANCELLED` - Update cancelled by admin or system

#### Signal Quality Monitoring Table
```sql
-- Cellular signal quality metrics from charge points
-- Defined in: backend/models.py:328-342
CREATE TABLE signal_quality (
    id SERIAL PRIMARY KEY,
    charger_id INTEGER REFERENCES charger(id) ON DELETE CASCADE,
    rssi INTEGER NOT NULL,      -- Received Signal Strength Indicator (0-31 for GSM, 99=unknown)
    ber INTEGER NOT NULL,        -- Bit Error Rate (0-7 for GSM, 99=unknown/not detectable)
    timestamp VARCHAR(50) NOT NULL,  -- Timestamp from charger
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_signal_quality_created ON signal_quality(created_at);
CREATE INDEX idx_signal_quality_charger ON signal_quality(charger_id);
```

**Data Source**: OCPP DataTransfer messages from JET_EV1 chargers

**Data Retention**: Records older than 90 days are automatically deleted by the data retention service

#### Charger Error Tracking (NEW)
```sql
-- OCPP StatusNotification error tracking
-- Defined in: backend/models.py:366-386
CREATE TABLE charger_error (
    id SERIAL PRIMARY KEY,
    charger_id INTEGER REFERENCES charger(id) ON DELETE CASCADE,
    connector_id INTEGER NOT NULL,
    status VARCHAR(50) NOT NULL,                    -- Charger status when error occurred
    error_code VARCHAR(50) NOT NULL,                -- Standard OCPP error code
    vendor_error_code VARCHAR(50),                  -- Vendor-specific error code
    vendor_id VARCHAR(255),                         -- Vendor identifier
    info VARCHAR(255),                              -- Additional error information
    error_timestamp TIMESTAMP,                      -- Timestamp from charger (if provided)
    is_resolved BOOLEAN DEFAULT FALSE,             -- Track if error was resolved
    resolved_at TIMESTAMP,                          -- When error was resolved
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_charger_error_charger ON charger_error(charger_id);
CREATE INDEX idx_charger_error_code ON charger_error(error_code);
CREATE INDEX idx_charger_error_vendor ON charger_error(vendor_error_code);
CREATE INDEX idx_charger_error_resolved ON charger_error(is_resolved);
CREATE INDEX idx_charger_error_created ON charger_error(created_at);
```

**Standard OCPP Error Codes**:
- `NoError`, `ConnectorLockFailure`, `EVCommunicationError`, `GroundFailure`
- `HighTemperature`, `InternalError`, `LocalListConflict`, `OtherError`
- `OverCurrentFailure`, `OverVoltage`, `PowerMeterFailure`, `PowerSwitchFailure`
- `ReaderFailure`, `ResetFailure`, `UnderVoltage`, `WeakSignal`

**Vendor Error Code Examples** (JET_EV1):
- `GF001` - Vendor-specific ground fault code
- `TEMP_CRIT_01` - Critical temperature exceeded
- `GSM_LOW_RSSI` - Low cellular signal strength

**Resolution Logic**: When charger sends StatusNotification with `error_code="NoError"`, all unresolved errors for that connector are marked as resolved.

#### QR Payment Tables (NEW)
```sql
-- Razorpay UPI QR codes linked to chargers
-- Defined in: backend/models.py (ChargerQRCode)
CREATE TABLE charger_qr_code (
    id SERIAL PRIMARY KEY,
    charger_id INTEGER REFERENCES charger(id) ON DELETE CASCADE,
    razorpay_qr_code_id VARCHAR(255) UNIQUE NOT NULL,  -- Razorpay's QR identifier
    image_url VARCHAR(500) NOT NULL,                    -- QR code image from Razorpay
    short_url VARCHAR(500),                             -- Short URL for sharing
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_charger_qr_code_razorpay ON charger_qr_code(razorpay_qr_code_id);

-- QR-based appless payment records
-- Defined in: backend/models.py (QRPayment)
CREATE TABLE qr_payment (
    id SERIAL PRIMARY KEY,
    charger_id INTEGER REFERENCES charger(id) ON DELETE CASCADE,
    charger_qr_code_id INTEGER REFERENCES charger_qr_code(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES app_user(id) ON DELETE SET NULL,     -- UPI_GUEST or discovered user
    transaction_id INTEGER REFERENCES transaction(id) ON DELETE SET NULL,  -- Linked OCPP transaction
    razorpay_payment_id VARCHAR(255) UNIQUE NOT NULL,    -- Razorpay payment identifier
    razorpay_qr_code_id VARCHAR(255) NOT NULL,           -- Denormalized QR code reference
    amount_paid DECIMAL(10,2) NOT NULL,                  -- Customer's payment in ₹
    customer_vpa VARCHAR(255),                           -- UPI VPA (e.g., user@okaxis)
    customer_name VARCHAR(255),                          -- Payer name from Razorpay
    customer_contact VARCHAR(255),                       -- Phone number from webhook
    energy_cost DECIMAL(10,2),                           -- Calculated after charging
    gst_amount DECIMAL(10,2),                            -- GST on energy_cost (18% default)
    platform_fee DECIMAL(10,2),                          -- Actual Razorpay fee (from webhook/API, fallback to 2% estimate)
    razorpay_commission DECIMAL(10,2),                   -- Base Razorpay commission (fee - tax)
    razorpay_gst DECIMAL(10,2),                          -- GST on Razorpay commission
    fee_source VARCHAR(20),                              -- 'webhook', 'api', or 'estimated'
    refund_amount DECIMAL(10,2),                         -- Amount refunded to customer
    razorpay_refund_id VARCHAR(255),                     -- Refund transaction ID
    status VARCHAR(20) NOT NULL,                         -- QRPaymentStatusEnum
    failure_reason TEXT,                                  -- Error description on failure
    metadata JSONB,                                      -- Raw webhook payload for debugging
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_qr_payment_razorpay ON qr_payment(razorpay_payment_id);
CREATE INDEX idx_qr_payment_qr_code ON qr_payment(razorpay_qr_code_id);
```

**QRPaymentStatusEnum Values**:
- `PAID` - Payment received, awaiting charging start
- `CHARGING` - Transaction linked and charging in progress
- `COMPLETED` - Charging done, no refund needed (or refund below minimum)
- `REFUNDED` - Charging done, unused balance refunded to customer
- `REFUND_FAILED` - Refund API call to Razorpay failed
- `EXPIRED` - Payment too old (>5 min) or plug-in timeout
- `FAILED` - Charger disconnected, RemoteStart rejected, or other failure

**User Model Extensions** (for QR):
- `upi_vpa VARCHAR(255)` - Unique nullable UPI address for VPA-based user lookup
- `auth_provider VARCHAR(20)` - Extended from VARCHAR(6) to support `UPI_GUEST` (was EMAIL, GOOGLE, CLERK)

#### Transaction Management
```sql
-- OCPP charging transactions
-- Defined in: backend/models.py:136-157
CREATE TABLE transaction (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES user(id),
    charger_id INTEGER REFERENCES charger(id),
    vehicle_id INTEGER REFERENCES vehicle_profile(id),
    start_meter_kwh DECIMAL(12, 3),
    end_meter_kwh DECIMAL(12, 3),
    energy_consumed_kwh DECIMAL(12, 3),
    energy_charge DECIMAL(10, 2),       -- energy_kwh × rate_per_kwh
    gst_amount DECIMAL(10, 2),          -- GST on energy_charge
    gst_rate_percent DECIMAL(5, 2) DEFAULT 18.00,  -- rate snapshot at billing
    total_billed DECIMAL(10, 2),        -- energy_charge + gst_amount
    start_time TIMESTAMP DEFAULT NOW(),
    end_time TIMESTAMP,
    stop_reason VARCHAR(50),
    transaction_status TransactionStatusEnum NOT NULL,  -- STARTED, PENDING_START, RUNNING, SUSPENDED, PENDING_STOP, STOPPED, COMPLETED, CANCELLED, FAILED, BILLING_FAILED
    suspended_at TIMESTAMP,          -- When transaction was suspended (charger reboot)
    resumed_at TIMESTAMP,            -- When transaction was resumed
    resume_count INTEGER DEFAULT 0,  -- Number of times transaction was resumed
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Real-time energy measurements
-- Defined in: backend/models.py:159-172
CREATE TABLE meter_value (
    id SERIAL PRIMARY KEY,
    transaction_id INTEGER REFERENCES transaction(id),
    reading_kwh DECIMAL(12, 3) NOT NULL,
    current DECIMAL(6, 2),      -- Amperes
    voltage DECIMAL(6, 2),      -- Volts
    power_kw DECIMAL(8, 3),     -- Kilowatts
    created_at TIMESTAMP DEFAULT NOW()
);
```

#### System Logging
```sql
-- Complete OCPP message audit trail
-- Defined in: backend/models.py:174-188
CREATE TABLE log (
    id SERIAL PRIMARY KEY,
    charge_point_id VARCHAR(100),
    message_type VARCHAR(100),
    direction MessageDirectionEnum NOT NULL,  -- IN/OUT
    payload JSONB,  -- Complete OCPP message
    status VARCHAR(50),
    correlation_id VARCHAR(100),  -- Request correlation
    timestamp TIMESTAMP DEFAULT NOW()
);
```

### Database Relationships & Constraints
1. **Foreign Key Integrity**: Complete referential integrity across all relationships
2. **Unique Constraints**: OCPP compliance (charge_point_string_id, serial_number)
3. **Cascade Operations**: Proper cleanup on entity deletion
4. **Enum Validation**: Database-level enum constraint enforcement
5. **Indexing Strategy**: Optimized indexes for OCPP operations (defined in migrations)

### Migration Management
- **Migration System**: Aerich-based schema versioning
- **Current Migrations** (13 total):
  - `0_20250810160500_init.py`: Initial schema creation
  - `1_20250812140852_add_billing_failed_status.py`: Billing system enhancement
  - `2_20251107131429_add_firmware_models.py`: Firmware file and update tables
  - `3_20251121122920_add_signal_quality_table.py`: Signal quality monitoring
  - `4_*_firmware_update_redesign_unique_charger_firmware.py`: Firmware uniqueness
  - `5_20260105100057_add_external_charger_id.py`: External charger ID
  - `6_20260113163547_add_admin_and_charger_error.py`: Admin + charger error tables
  - `7_20260303073846_add_audit_and_webhook_tables.py`: Audit events + webhook events
  - `8_20260305050220_add_transaction_resume_fields.py`: Transaction resume/suspend
  - `9_20260306093240_add_audit_composite_index.py`: Audit table indexing
  - **`10_20260310000000_add_qr_payment_models.py`**: ChargerQRCode + QRPayment tables + upi_vpa column
  - **`11_20260310000100_widen_auth_provider_column.py`**: auth_provider VARCHAR(6) → VARCHAR(20) for UPI_GUEST
  - **`12_20260315154019_allow_qr_regeneration_drop_admin.py`**: Drop unique charger QR constraint + drop admin_user table
- **Migration Commands**:
  ```bash
  # Located in: backend/pyproject.toml
  aerich migrate --name "description"  # Generate
  aerich upgrade                       # Apply
  # Docker: make prod-migrate
  ```

---

## OCPP 1.6 Implementation

### Message Handler Architecture
**Location**: `backend/main.py:64-387`
**Pattern**: Event-driven message handling with async processing

### Core OCPP Messages

#### 1. BootNotification Handler
```python
# Implementation: backend/main.py:163-224
@on('BootNotification')
async def on_boot_notification(self, charge_point_vendor, charge_point_model, **kwargs):
```

**Business Logic**:
- Validates charger registration in database
- Sets 30-second heartbeat interval
- Updates charger firmware_version, vendor, model from BootNotification payload
- **Transaction Suspend/Resume**: On disconnect, `disconnect_handler.py` suspends active transactions with a 180s timeout (`DISCONNECT_SUSPEND_TIMEOUT_SECONDS`). On BootNotification, already-SUSPENDED transactions get their timeout reset (CAS guard invalidates old timeout), and a new 300s resume window starts (`SUSPEND_TIMEOUT_SECONDS`). Still-active transactions (edge case) are suspended as before. Auto-stop with billing + QR refund on timeout expiry. The per-txn loop body is extracted into `_handle_ongoing_transaction_on_boot()` for testability.
- **Resume staleness guard**: every BootNotification per-txn handler call (and the MeterValues + GetLastMeterValue resume points) goes through `transaction_finalizer.is_resume_too_stale()` first. If the gap exceeds `MAX_RESUME_GAP_SECONDS` (default 900s), the txn is finalized with stop_reason `STALE_RECONNECT` instead of being suspended/resumed. This is defense-in-depth for the case where the disconnect handler silently failed to mark SUSPENDED — see the "Resume Staleness Guard" subsection under Transaction Finalizer above.
- Resume fields tracked: `suspended_at`, `resumed_at`, `resume_count`
- Comprehensive connection logging

**Response**: OCPP-compliant BootNotificationResponse with "Accepted" status

#### 2. Heartbeat Handler
```python
# Implementation: backend/main.py:104-117
@on('Heartbeat')
async def on_heartbeat(self, **kwargs):
```

**Features**:
- Updates database heartbeat timestamp
- Maintains Redis connection state
- 90-second timeout monitoring
- Connection liveness validation

#### 3. StatusNotification Handler
```python
# Implementation: backend/main.py:243-377
@on('StatusNotification')
async def on_status_notification(self, connector_id, status, error_code=None, info=None,
                                  vendor_error_code=None, vendor_id=None, timestamp=None, **kwargs):
```

**OCPP 1.6 Status Support**:
- `Available`: Ready for new transaction
- `Preparing`: Preparing for transaction start
- `Charging`: Active energy transfer
- `SuspendedEVSE`: Suspended by charging station
- `SuspendedEV`: Suspended by electric vehicle
- `Finishing`: Transaction completion in progress
- `Reserved`: Reserved for specific user
- `Unavailable`: Not available for charging
- `Faulted`: Error condition present

**Transaction Failure Detection** (connector-type-aware):
- When status transitions to a non-charging state while a transaction is active, behavior depends on connector type:
  - **Type 2/CCS/CHAdeMO**: Immediately fails transaction with billing + QR refund
  - **Socket chargers (Mode 1&2)**: `Available` status triggers a 5-minute grace period via Redis (`socket_grace:{charge_point_id}`). If MeterValues arrive during grace, transaction stays alive. If not, transaction fails after timeout via `_socket_grace_timeout()`.
  - `Faulted`/`Unavailable`/`Reserved` always trigger immediate failure regardless of connector type
- Socket detection uses `charger_type_service.is_socket_charger_cached()` with in-memory cache populated at BootNotification
- **Charging states** (no auto-fail): `Charging`, `Preparing`, `SuspendedEVSE`, `SuspendedEV`, `Finishing`
- **Non-charging states**: `Available` (grace period for socket), `Reserved`, `Unavailable`, `Faulted` (always immediate)

**Error Tracking**:
- Captures standard OCPP error codes (e.g., `GroundFailure`, `HighTemperature`)
- Captures vendor-specific error codes via `vendorErrorCode` field
- Stores errors in `charger_error` table with timestamps
- Auto-resolves errors when `error_code="NoError"` is received
- Supports full error history with resolution tracking

#### 4. StartTransaction Handler
```python
# Implementation: backend/main.py
@on('StartTransaction')
async def on_start_transaction(self, connector_id, id_tag, meter_start, timestamp, **kwargs):
```

**Business Logic**:
- User validation via RFID card ID lookup
- Vehicle profile creation/retrieval
- Transaction record creation with RUNNING status
- Energy meter initialization (Wh to kWh conversion)
- **QR Integration**: Calls `QRPaymentService.link_transaction_to_qr_payment()` to link OCPP transaction to pending QR payment and cache budget in Redis
- Comprehensive error handling and logging

#### 5. StopTransaction Handler
```python
# Implementation: backend/main.py
@on('StopTransaction')
async def on_stop_transaction(self, transaction_id, meter_stop, timestamp, **kwargs):
```

**Business Logic**:
- Transaction finalization with end meter reading
- Energy consumption calculation
- Status update to COMPLETED
- **Billing Integration**: Automatic wallet billing via WalletService
- **QR Billing**: Calls `QRPaymentService.process_qr_session_billing()` to calculate final cost and issue partial refund for unused balance
- Error handling for billing failures (sets BILLING_FAILED status)

**Invalid Stop Reason Handling**:
- The `ChargePoint.route_message()` override sanitizes non-standard `reason` values (e.g., firmware sending `"AppStop"`) to `"Other"` before OCPP schema validation
- Prevents the `ocpp` library from rejecting the entire `StopTransaction` message due to a `FormatViolationError` on an invalid enum value
- Valid OCPP 1.6 reasons: `EmergencyStop`, `EVDisconnected`, `HardReset`, `Local`, `Other`, `PowerLoss`, `Reboot`, `Remote`, `SoftReset`, `UnlockCommand`, `DeAuthorized`

#### 6. MeterValues Handler
```python
# Implementation: backend/main.py:263-387
@on('MeterValues')
async def on_meter_values(self, connector_id, meter_value, transaction_id=None, **kwargs):
```

**Supported Measurands**:
- `Energy.Active.Import.Register`: Cumulative energy (Wh → kWh)
- `Current.Import`: Current flow (mA → A)
- `Voltage`: Voltage level (mV → V)
- `Power.Active.Import`: Active power (W → kW)

**Features**:
- Multi-measurand processing per timestamp
- Unit conversion automation
- Database persistence for energy analytics
- Transaction association validation
- **QR Budget Check**: Calls `QRPaymentService.check_budget_and_auto_stop()` to compare current cost against customer's prepaid budget; schedules RemoteStopTransaction as background task if budget exceeded

#### 7. FirmwareStatusNotification Handler
```python
# Implementation: backend/main.py:522-597
@on('FirmwareStatusNotification')
async def on_firmware_status_notification(self, status, **kwargs):
```

**OCPP 1.6 Firmware Status Support**:
- `Idle`: No update in progress
- `Downloading`: Firmware download active
- `Downloaded`: Download complete, awaiting installation
- `Installing`: Installation in progress
- `Installed`: Update successful ✅
- `DownloadFailed`: Download error ❌
- `InstallationFailed`: Installation error ❌
- `InstallVerificationFailed`: Verification error ❌

**Business Logic**:
- Finds active FirmwareUpdate record for charger
- Maps OCPP status to database FirmwareUpdateStatusEnum
- Tracks timestamps: `started_at` (when downloading), `completed_at` (when finished/failed)
- **On SUCCESS (Installed)**: Updates `charger.firmware_version` to new version
- **On FAILURE**: Stores error message in FirmwareUpdate record
- Complete audit logging to OCPPLog table

**Status Workflow**:
```
PENDING → Downloading → Downloaded → Installing → Installed
                ↓              ↓            ↓
         DownloadFailed  (skip)  InstallationFailed
```

#### 8. DataTransfer Handler
```python
# Implementation: backend/main.py:599-668
@on('DataTransfer')
async def on_data_transfer(self, vendor_id: str, message_id: str = None, data: str = None, **kwargs):
```

**Purpose**: Handle vendor-specific data messages from charge points

**Vendor Support**:
- **JET_EV1**: Signal quality data (RSSI, BER)
- **GetLastMeterValue**: Transaction resume support — charger requests last meter reading for a transaction ID, server responds with the last known reading so the charger can resume from the correct point
- **PostBootState (server→charger)**: After every BootNotification, server pushes meter value and pending transaction state via `@after('BootNotification')` hook. Payload includes `hasPendingTransaction`, `lastMeterValueWh`, and optionally `transactionId`/`startMeterValueWh`/`energyConsumedWh`.

**JET_EV1 Signal Quality Data Format**:
```json
{
  "rssi": 22,   // Received Signal Strength Indicator (0-31 for GSM, 99=unknown)
  "ber": 99,    // Bit Error Rate (0-7 for GSM, 99=unknown/not detectable)
  "timestamp": "86"
}
```

**Business Logic**:
- Routes to vendor-specific handlers based on `vendor_id`
- Validates required fields (rssi, ber)
- Range validation: RSSI (0-31 or 99), BER (0-7 or 99)
- Stores in `SignalQuality` database table
- Returns status: Accepted, UnknownVendorId, UnknownMessageId, or Rejected

**Use Case**: Monitoring cellular signal strength for charge points with modem connectivity

### Remote Commands (Central System → Charge Point)

#### 1. RemoteStartTransaction
```python
# Implementation: backend/main.py:480-484
# API Integration: backend/routers/chargers.py:185-206
```

**Usage**:
- Initiated via admin dashboard or API
- Requires user ID tag and optional connector ID
- Real-time command execution with status feedback
- **Socket charger support**: Allows remote start from `Available` state (Type 2 requires `Preparing`)

#### 2. RemoteStopTransaction
```python
# Implementation: backend/main.py:485-489
# API Integration: backend/routers/chargers.py:208-228
```

**Usage**:
- Transaction ID-based termination
- Admin override capabilities
- Automatic billing processing on success

#### 3. ChangeAvailability
```python
# Implementation: backend/main.py:490-494
# API Integration: backend/routers/chargers.py:230-250
```

**Modes**:
- `Operative`: Enable charging functionality
- `Inoperative`: Disable charging functionality
- Connector-specific or entire charge point control

#### 4. UpdateFirmware
```python
# Implementation: backend/main.py:809-813
# API Integration: backend/routers/firmware.py:270-350 (single), 353-449 (bulk)
```

**Purpose**: Trigger firmware over-the-air (OTA) update on OCPP charge points

**Payload**:
```python
{
    "location": "https://server.com/firmware/1.0.0_firmware.bin",  # Download URL
    "retrieve_date": "2025-11-28T12:00:00.000Z",                   # ISO 8601
    "retries": 3,                                                   # Retry attempts
    "retry_interval": 300                                           # Seconds between retries
}
```

**Pre-Update Safety Checks** (`routers/firmware.py:236-267`):
1. **Online Validation**: Heartbeat within 90 seconds
2. **Transaction Check**: No active charging sessions (STARTED, PENDING_START, RUNNING)
3. **Version Warning**: Alert if updating to same version

**Update Flow**:
1. Admin triggers via `/api/admin/firmware/chargers/{id}/update`
2. Server validates charger state
3. Creates FirmwareUpdate database record (PENDING status)
4. Sends OCPP UpdateFirmware command with download URL
5. Charger downloads firmware and sends FirmwareStatusNotification updates
6. Server tracks progress via FirmwareStatusNotification handler
7. On success: Updates charger.firmware_version

**Monitoring**:
- Real-time dashboard: `GET /api/admin/firmware/updates/status`
- Per-charger history: `GET /api/admin/firmware/chargers/{id}/history`
- Frontend auto-refresh: 10-second polling interval

**Non-OCPP Alternative**:
For charge points without OCPP support, use public API:
```bash
curl https://server.com/api/firmware/latest
# Returns: {version, filename, download_url, checksum, file_size}
```

#### 5. DataTransfer (PostBootState)

**Purpose**: Send vendor-specific data (VOLTLYNC PostBootState for meter restore + transaction resume)

**Usage**:
- Automatically triggered after every BootNotification via `@after('BootNotification')` hook
- Pushes meter value and pending transaction state to charger
- Charger resumes by sending MeterValues or StopTransaction

### Connection Management Architecture

#### Connection Manager (`backend/core/connection_manager.py`)
**Purpose**: Singleton managing all active charge point WebSocket connections

**Key Features**:
- **Connected chargers dict**: Maps `charge_point_id` → `{websocket, cp, heartbeat_task, connected_at, last_seen}`
- **Tombstone mechanism**: 100ms tombstone on disconnect to prevent reconnection races
- **Heartbeat monitor**: 15-second check for OCPP activity; auto-disconnect after 120s inactivity
- **Periodic cleanup**: 5-minute background task to clean stale connections
- **OCPP command dispatch**: `send_ocpp_request()` for RemoteStart, RemoteStop, ChangeAvailability, UpdateFirmware, Reset

**WebSocket Adapters**:
- `FastAPIWebSocketAdapter`: Basic send/recv wrapper for OCPP library compatibility
- `LoggingWebSocketAdapter`: Validates OCPP messages, logs IN/OUT with correlation IDs, detects AT command firmware bugs, ghost session detection

#### Heartbeat Monitoring

**Configuration**:
- **Timeout**: 120 seconds of inactivity
- **Check Frequency**: Every 15 seconds
- **Cleanup Trigger**: Automatic dead connection removal with `force_disconnect()`
- **Disconnect Callbacks**: `force_disconnect()` fires registered callbacks (e.g. transaction suspension) via `register_on_disconnect()`
- **Periodic Cleanup**: Every 5 minutes, scans all connections for staleness

#### Connection Validation
**Location**: `backend/crud.py`
**Features**:
- Database charger existence validation
- Duplicate connection prevention (tombstone-based)
- Redis state synchronization
- Connection metadata tracking

---

## Authentication & Authorization

### Clerk Integration Architecture

#### Backend Authentication (`backend/auth_middleware.py`)
**Purpose**: JWT validation and role-based access control

**JWT verification** uses `jwt.PyJWKClient` from PyJWT. A module-level client caches Clerk's JWKS (1-hour TTL) and auto-refreshes on unknown `kid`. The `verify_token()` function:
1. Fetches the signing key for the token's `kid` via `PyJWKClient.get_signing_key_from_jwt(token)`
2. Calls `jwt.decode(token, key, algorithms=["RS256"], issuer=CLERK_ISSUER)` — RS256 signature and issuer are validated
3. Looks up the user role from the local DB (not JWT claims) to enforce current role

**Environment variables:**
- `CLERK_SECRET_KEY` — Clerk secret (required)
- `CLERK_JWKS_URL` — JWKS endpoint (prod: `https://clerk.voltlync.com/.well-known/jwks.json`)
- `CLERK_ISSUER` — Expected `iss` claim (prod: `https://clerk.voltlync.com`)
- `CORS_ORIGINS` — comma-separated allowlist (prod: `https://app.voltlync.com`)

If `CLERK_JWKS_URL` is unset, the module logs a warning and derives a dev-tenant URL from the secret key for development convenience only.

**Features**:
- **JWT Validation**: RS256 signature check against Clerk JWKS + issuer verification
- **Role Extraction**: Role sourced from DB (not JWT), allowing admin revocation without token rotation
- **Request Context**: User information injection for route handlers
- **Error Handling**: Distinct 401 responses for expired, invalid-signature, and invalid-issuer tokens

**Protected Route Patterns**:
- `/api/admin/*`: Requires ADMIN role
- `/users/*`: Requires authentication (any role)
- `/auth/*`: Public authentication endpoints

#### Frontend Authentication (`frontend/middleware.ts`)
**Purpose**: Route-level protection and role-based redirects

```typescript
// Implementation: frontend/middleware.ts
export default clerkMiddleware((auth, req) => {
```

**Features**:
- **Route Protection**: Automatic authentication checks
- **Role-Based Redirects**: Admin vs User dashboard routing
- **Session Management**: Automatic token refresh handling
- **Public Route Handling**: Sign-in/sign-up accessibility

#### Admin-Onboarded Users: Invitation + Role Sync

Franchisee users are created by admins in the DB first, then invited into
Clerk rather than asked to self-sign-up. The flow:

1. `POST /api/admin/franchisees` creates the `Franchisee` + `User(role=FRANCHISEE)` rows inside one transaction.
2. `services/clerk_invitation_service.send_invitation()` calls Clerk's
   `invitations.create` with `public_metadata={"role": "FRANCHISEE"}` and
   `redirect_url = FRONTEND_URL + /franchisee`. Clerk emails the magic
   link.
3. User clicks link → Clerk creates the auth account, copying the
   invitation's `public_metadata` onto the user.
4. Clerk fires `user.created` webhook → `routers/webhooks.py` matches the
   existing DB User by email, attaches `clerk_user_id`. If the Clerk
   `public_metadata.role` drifts from the DB role (user signed up
   without the invitation link, metadata was stripped, etc.) the
   handler calls `clerk_invitation_service.push_role_to_clerk()` to
   re-sync — important because the frontend middleware routes on the
   Clerk session claim, not the DB.
5. Admin can resend the invitation via
   `POST /api/admin/franchisees/{id}/resend-invitation`, which revokes
   any pending invitation first so the newest email wins.

Authority: **DB `User.role` is the source of truth.** Clerk
`public_metadata.role` is a mirror, kept consistent by the invitation at
creation time and the webhook self-heal at first login.

Env vars required for this flow: `CLERK_SECRET_KEY`, `CLERK_WEBHOOK_SECRET`, `FRONTEND_URL`.

#### Payer-Payee Transparency on QR Codes (RBI Route Compliance)

The Razorpay QR code a customer scans at a charger is a PNG that Razorpay
generates server-side. The **big bold label on that image is the owning
merchant's legal business name as registered during KYC** — it is *not*
something we pass via the `name` field in the API payload.

Current model: **all QRs are platform-owned**. Every UPI payment lands
in VoltLync's nodal balance first; the franchisee's share is disbursed
via a Razorpay Route transfer after the charging session settles. This
keeps fund flow auditable from a single point and lets refunds execute
from the platform nodal without needing to claw money back from a
franchisee. The QR image therefore displays "VOLTLYNC PRIVATE LIMITED";
the franchisee's business name is included in the QR *description*
(shown under the big label on Razorpay's rendered image and in the
customer's UPI app transaction history) but not as the payee.

Implementation notes:

1. `services/razorpay_service.create_qr_code` still accepts an
   `account_id` parameter (forwarded as `X-Razorpay-Account`) for
   backward-compatible close/fetch on legacy QRs, but new QRs are
   always created with `account_id=None` (see
   `routers/qr_codes._create_qr_for_charger` and
   `routers/franchisee_portal._create_franchisee_qr`).
2. `ChargerQRCode.owner_razorpay_account_id` remains on the model for
   legacy rows; on new rows it is always NULL.
3. Franchisees can still create/regenerate/close their chargers' QRs
   via `/franchisee/qr-codes`, but the `can_create_direct` flag now
   always returns False since franchisee-scoping is disabled
   platform-wide.
4. Route transfer lifecycle: settlement service creates a
   `CommissionLedgerEntry` after QR billing + refund complete, then
   `initiate_transfer` picks one of two Razorpay endpoints based on
   whether the ledger entry carries a source `razorpay_payment_id`:
   - **QR sessions** → `create_payment_transfer` → `POST /v1/payments/
     {payment_id}/transfers` (no on-demand activation needed; Razorpay
     enforces `sum(transfers) ≤ captured_amount`). Each call writes a
     `RazorpayApiLog` audit row with full request/response wire data.
     Application-level idempotency: `_validate_ledger_for_transfer`
     rejects a second ledger row with the same `razorpay_payment_id`.
   - **Wallet sessions** → `create_transfer` → `POST /v1/transfers`
     with `X-Transfer-Idempotency` header. **This endpoint requires an
     on-demand Razorpay merchant feature** ("Direct Transfers"); until
     ops opens a support ticket against the parent merchant the call
     fails with `400 "This feature is not enabled for this merchant."`
     The retry service will keep marking these `FAILED` until the flag
     flips.

   The franchisee's Route account status (`transfers_enabled`,
   `funds_on_hold`) gates every transfer attempt; when gated, the
   entry is marked `ON_HOLD` and retried automatically when a
   subsequent `account.funds_unhold` / `account.activated` webhook
   flips the gate off. A separate **24-hour cooling-period guard** in
   `initiate_transfer` parks transfers as `ON_HOLD` with
   `failure_reason="cooling_period"` when `franchisee.activated_at`
   is within the last 24h — Razorpay rejects transfers in that
   window.

5. **KYC payload shape** (post-2026-04 audit; documented to prevent
   regression of the `acc_Sg73UwyOU3jziR` stuck-account pattern):
   - `create_linked_account` payload sends `type: "route"` (canonical
     and required per Razorpay's `create-linked-account` API spec) and
     `addresses.registered` only — Razorpay rejects `operational` for
     `business_type: individual` with `"operational is/are not required
     and should not be sent"` (caught 2026-04-29 via the new audit log).
     After create, a WARNING is logged if Razorpay echoes a different
     `business_type` than we sent (Razorpay silently downgraded
     `individual` → `not_yet_registered` for `acc_Sg73UwyOU3jziR`).
     `profile.category/subcategory` is hardcoded to
     `services / automotive_service_shops` (lowercase). Razorpay's
     enum is **lowercase-strict** — UPPERCASE 400s with
     `"Invalid business subcategory"`. Earlier values
     (`utilities/electric_vehicle_charging`, then
     `services/service_stations`) were silently rejected by KYC
     review and parked accounts in `needs_clarification +
     requirements: []` (broken Razorpay-side state machine — the
     subcategory rejection isn't surfaced through `requirements[]`).
     Diagnostic PATCH on `acc_SjK7ZBzAfiA4QF` (2026-04-30) confirmed
     `automotive_service_shops` activates immediately; see
     `docs/razorpay-onboarding-acc_SjK7ZBzAfiA4QF.md` "Resolution"
     section and project memory `project_razorpay_subcategory_fix`.
   - `add_stakeholder` derives `(director, executive)` defaults from
     the franchisee's `business_type` via `_relationship_defaults` —
     INDIVIDUAL/PROPRIETORSHIP get `(False, True)` (no "director" of an
     individual), corporate types get `(True, True)`. Stakeholder
     payload includes `kyc.pan` and optional `addresses.residential`.
   - `submit_bank_details` PATCH includes `tnc_accepted: true` (per
     Razorpay's `update-product-config` doc) and the three documented
     settlement fields (`account_number`, `ifsc_code`,
     `beneficiary_name`) only. **`account_type` is NOT sent** —
     Razorpay rejects it with "account_type is/are not required and
     should not be sent" despite being on bank-account schemas
     elsewhere (verified 2026-04-29 via the audit log on a fresh
     onboarding). The `Franchisee.bank_account_type` column stays for
     invoicing / reconciliation use.
     **Name-chain advisory (not enforced):** Razorpay requires the
     bank passbook account-holder name == `settlements.beneficiary_name`
     (PATCH product config) == `legal_business_name` (POST /v2/accounts).
     Today `beneficiary_name` is `franchisee.bank_account_name` and
     `legal_business_name` is `franchisee.business_name` — two
     independent admin inputs with no equality guarantee. The
     franchisee detail page surfaces an advisory note in the Bank
     Account section. Hard enforcement is pending confirmation that
     the rule applies uniformly across all `business_type` values.
   - **Pre-transfer validator** (`_validate_ledger_for_transfer` in
     `franchisee_settlement_service.py`) runs six foolproof checks
     before any `create_transfer` SDK call: positive payout, payout ≤
     gross − refund, components sum to gross within a 2-paisa
     tolerance, settlement_status not in a terminal state, franchisee
     has a matching razorpay_account_id, and razorpay_payment_id
     (when present) hasn't already been used on a sibling ledger
     entry's transfer. Math/state failures mark the entry FAILED with
     a `validation_*` `failure_reason` and do NOT increment
     retry_count — they require admin investigation. Razorpay-side
     audit linkage is achieved by enriching the transfer's `notes`
     dict with `transaction_id`, `ledger_entry_id`, `franchisee_id`,
     `voltlync_payment_id` (source payment_id or "wallet"), and
     `idempotency_key`.
   - **Background payout retry service**
     (`services/franchisee_payout_retry_service.py`, mirrors the
     `data_retention_service` pattern) wakes every
     `FRANCHISEE_PAYOUT_RETRY_INTERVAL_SECONDS` (default 600) and
     calls `retry_failed_transfers()` to drain ON_HOLD/FAILED entries
     after cooling-period / funds_unhold gates clear. Started from
     `main.py:@app.on_event("startup")`; no-op when
     `RAZORPAY_ROUTE_ENABLED != "true"`. Closes the manual-retry-only
     gap that previously left `account.funds_unhold` and
     `account.activated` webhook firings without an automated trigger.
   - `update_stakeholder` (PUT
     `/api/admin/franchisees/{id}/stakeholders/{sid}`) PATCHes an
     existing Razorpay stakeholder so admins can backfill PAN /
     residential address without recreating.
   - `handle_account_webhook` correctly parses `requirements` as a list
     of `{field_reference, resolution_url, reason_code, status}` dicts
     (NOT a dict — fixed in migration-23 era code) and persists
     Razorpay's `verification` subtree on `Franchisee.kyc_verifications`
     (JSONB) so admins can see per-dimension KYC progress beyond the
     top-level `activation_status`.

6. **Outbound API audit log (migration-24 era)**:
   `services/razorpay_service._audit_call` is an async helper that wraps
   every mutating onboarding-chain SDK call (`account.create`,
   `account.edit`, `account.delete`, `stakeholder.create`,
   `stakeholder.edit`, `product.requestProductConfiguration`,
   `product.edit`) and writes one row to the `razorpay_api_log` table
   capturing method, endpoint, request body, response status,
   response body, success flag, and error message. PII keys
   (`pan`, `account_number`, `ifsc_code`, `aadhaar`, `gst`, `gstin`,
   `tan`, `card_number`, `card_id`) are masked to `***LAST4` via the
   `_mask_sensitive` recursive helper. Audit-write failures are
   swallowed so the SDK call result is preserved. Read-only fetches and
   high-volume calls (transfers, refunds, payments, QR ops) are
   intentionally NOT logged — they have idempotency keys as their audit
   anchor. The table mirrors `webhook_event` (inbound), giving symmetric
   end-to-end traceability for any Razorpay-side dispute. FK to
   `franchisee` uses `ON DELETE SET NULL` so logs survive franchisee
   deletion while staying joinable.

7. **Hard-delete linked account flow (admin self-serve)**:
   `DELETE /api/admin/franchisees/{id}/razorpay-account`, orchestrated
   by `FranchiseeOnboardingService.delete_linked_account`. Order: call
   Razorpay `DELETE /v2/accounts/{id}` first (audit-logged), then in a
   `tortoise.transactions.in_transaction()` block delete
   `franchisee_stakeholder` rows and clear all `razorpay_*` / `kyc_*` /
   `activated_at` / `status_reason` fields on the franchisee with
   `status` reset to `DRAFT`. Safety: refuses if any
   `CommissionLedgerEntry` rows exist for the franchisee (no force
   flag). Idempotent on already-cleared local state. Tolerates Razorpay
   404 / "not found" errors so admins can re-run after a partial
   failure. Frontend confirmation dialog requires typing the exact
   `acc_*` ID before the destructive button is enabled.

8. **Per-franchisee financial rollup on admin reads**:
   `FranchiseeResponse` carries two derived totals — `total_invoiced`
   and `total_transferred` — populated by helpers in
   `routers/franchisees.py`. `total_invoiced` =
   `SUM(GSTInvoice.total_amount)` for the franchisee (gross,
   GST-inclusive). `total_transferred` =
   `SUM(CommissionLedgerEntry.franchisee_payout)` filtered by
   `settlement_status IN (TRANSFER_PROCESSED, SETTLED)` so
   pending/failed/on-hold entries are excluded — the value reflects
   money actually moved to the franchisee. `list_franchisees` batches
   both aggregations with a single `group_by("franchisee_id")` query
   per metric to avoid N+1 on the admin list page; `get_franchisee`
   runs single-id sums. The fields are surfaced as two columns on the
   `/admin/franchisees` table and two overview cards on the
   `/admin/franchisees/[id]` detail page (formatted via
   `frontend/lib/utils.ts::formatINR`).

Complementary transparency surfaces (all read-only, franchisee name
sourced from the `Charger → Station → Franchisee` FK chain):

- `/api/public/stations` and `/api/public/stations/map` include `franchisee_name` on each station.
- `/api/public/qr-transactions` returns `franchisee_name` and `station_name` alongside `charger_name` for transaction history.
- `/api/users/charger/{id}` surfaces `station.franchisee_name`.
- The `/my-charges`, `/stations`, `/charge/[id]` and `StationMap` popup all render an "Operator:" line when populated.
- The GST invoice PDF has always included the franchisee's business name as the supplier (no change needed there).

### GST Tax Invoicing

**Supplier identity: VoltLync, always.** Every customer-facing GST invoice carries VoltLync's name, GSTIN, address, and state code in the `supplier_*` columns. VoltLync is the GST merchant-of-record (Razorpay Route MOR model): customers pay VoltLync, VoltLync remits output GST, and franchisees receive their share via Route transfer.

**Franchisee as substore (Razorpay disclosure).** Razorpay's payer-payee transparency rule requires that customers can clearly identify the payee when a third party delivers the goods or service. Since franchisees physically operate the chargers, every invoice tied to a franchisee-owned station snapshots the franchisee's `business_name`, `gstin`, `address`, `state`, and `state_code` onto the row and renders an "Operated by" block on the PDF below the VoltLync supplier block. Invoices for VoltLync-owned stations omit the block entirely. The `franchisee_id` FK on the invoice drives both this disclosure and the per-franchisee numbering (see Sequencing).

Per-session, customer-facing tax invoice generated for every completed charging session. Schema and code live in:
- `backend/models.py` — `GSTInvoice`, `GSTInvoiceCounter`
- `backend/services/invoice_service.py` — generation + PDF rendering
- `backend/routers/invoices.py` — list endpoints, PDF redirect
- `backend/services/s3_service.py` — PDF persistence (S3, lazy)

**Sequencing.** Invoice numbers are issued per `(franchisee_id, series, financial_year)` — each franchisee operates as a substore with its own running sequence. `series` is `WAL` for wallet-funded sessions, `QR` for UPI-guest sessions. Format:

- `VL/F{franchisee_id}/{SERIES}/{FY_NODASH}/{SEQ:05d}` — franchisee-owned station (e.g. `VL/F5/QR/202627/00017`)
- `VL/{SERIES}/{FY_NODASH}/{SEQ:05d}` — VoltLync-owned station (e.g. `VL/QR/202627/00001`)

The counter row is incremented under `SELECT FOR UPDATE` and the full `generate_invoice` call holds a row lock on the underlying `transaction` to prevent gaps from concurrent callers. Migration 28 briefly consolidated counters across franchisees; migration 29 reverted to per-franchisee sequences (with snapshot fields added) to satisfy Razorpay disclosure.

**Tax math.** `gst_rate_percent` is snapshotted onto the `transaction` row at billing time (from `tariff.gst_percent`). The invoice reads stored taxable values directly — `energy_taxable_value = transaction.energy_charge`, `gateway_charges = qr_payment.razorpay_commission`. No reverse-calc from a tax-inclusive total. CGST+SGST (intra-state) vs IGST (inter-state) is decided by comparing `supplier_state_code` to the station's `state_code`; the latter is frozen on the invoice as `place_of_supply_state_code`.

**Compliance guards.**
- A tax invoice without supplier GSTIN is not valid under CGST Rule 46. `generate_invoice` aborts and logs an error when the supplier (`Franchisee.gstin` or `VOLTLYNC_GSTIN`) is empty.
- HSN/SAC defaults to `996749` on the invoice; per-tariff `hsn_sac_code` overrides it when set.
- GST state codes are 2-digit numeric (per CBIC). Mismatched alpha codes (e.g. `"KL"`) would silently break the intra-state check; normalise via `backend/scripts/backfill_gst_schema.py` if older rows are found.
- **Internal-role skip.** Sessions whose `Transaction.user.role` is `ADMIN` or `FRANCHISEE` are treated as operational (admin test/courtesy charges, franchisees remote-starting their own stations for diagnostics) and never receive an invoice. The guard sits in `generate_invoice` immediately after the energy check, returns `None`, and increments the `Custom/Invoice/InternalRoleSkipped` metric. No invoice number is consumed, keeping the per-(franchisee, series, FY) sequence clean of internal events. Customer roles (`USER`, `UPI_GUEST`) are unaffected. Going-forward only — existing invoices for past admin/franchisee sessions are left as-is.

**Refunds.** Credit notes and refund vouchers are not modelled. The invoice's `transaction_amount` is net of refund (`amount_paid − refund_amount` for QR sessions). When B2B customers (with claimable Input Tax Credit) are introduced, a `gst_credit_note` table and IRP integration (IRN/signed QR/cancellation ack) will need to be added — schema today is B2C-only.

**PDF persistence.** PDFs are rendered with ReportLab and uploaded to S3 lazily on first download request. `gst_invoice.pdf_url` stores the S3 key; downloads redirect to a 15-minute presigned URL. Env vars: `AWS_S3_INVOICE_BUCKET`, `AWS_REGION`. Credentials resolve via the EC2 instance role on staging/prod and via `AWS_PROFILE=voltlync` locally.

**Branding overlay.** Every PDF page is stamped with the voltNOW A4 header/footer image (`backend/assets/invoice_header_footer.png`, 1241×1754 px ≈ 150 DPI) via a `_draw_branding` closure passed as both `onFirstPage` and `onLaterPages` to `doc.build`. Top/bottom margins on `SimpleDocTemplate` are 38 mm / 22 mm respectively so flowable content never overlaps the lime "EV Charging" header band or the lime footer band. The asset path is resolved relative to `services/invoice_service.py`; if the file is absent the renderer logs a warning and falls back to the legacy 15 mm margins so production is never broken by a missing asset.

**Cancellation.** Invoices are immutable once issued. Cancellation columns (`status`, `cancelled_at`, `cancellation_reason`) and the orphaned `gst_credit_note` table were removed in migration 27.

**Admin "GST Filings" window.** `/admin/gst-filings` (frontend page at `frontend/app/admin/gst-filings/page.tsx`) is the accountant-facing UI: filterable, tally-friendly table of every `gst_invoice` row plus top-of-page totals. The default row shows the lean tally column set — Invoice#, Date, Series, Customer, Operated by, HSN, kWh, Taxable ₹, GST %, CGST ₹, SGST ₹, IGST ₹, Total ₹, Refund ₹ — and clicking a row expands an inline detail panel with the remaining PDF-bill values (place of supply / inter-state flag, station + location, charger + connector, charged-on, duration, tariff/kWh, energy and gateway line breakdowns with their HSNs, total tax, payment method, transaction ₹, amount in words). PoS was dropped from the main row in favour of the expanded panel; the GSTR-1 CSV still carries it. Backed by three admin-only endpoints in `backend/routers/invoices.py`:
- `GET /api/admin/invoices` — paginated list with filters: `financial_year`, `series`, `franchisee_id`, `start_date`/`end_date` (ISO 8601 with TZ, applied to `invoice_date`), `place_of_supply_state_code`, `is_inter_state`, `q` (free-text matches invoice number / customer name / customer identifier). The JSON projection (`_invoice_to_dict`) carries the full PDF-equivalent field set so the UI can render the detail panel without extra round-trips.
- `GET /api/admin/invoices/summary` — aggregates (count, total taxable, CGST/SGST/IGST sums, total amount, by-series counts) over the same filtered set.
- `GET /api/admin/invoices/export.csv` — streaming flat CSV with one row per invoice and a superset of every UI-visible column (tariff_rate_incl_tax, charged_on, duration_seconds, gateway_hsn_code, station_location, connector_type, supplier/customer addresses, amount_in_words). Filename `gst_invoices_{fy_or_all}_{YYYY-MM-DD}.csv`. Memory stays flat regardless of result size — rows yielded one at a time via `StreamingResponse`. Sectional GSTR-1 exports (B2C state-wise, HSN summary) are deliberately out of scope; revisit if the CA explicitly needs them.

### Role-Based Access Control (RBAC)

#### Role Definitions
```python
# Defined in: backend/models.py:12-15
class UserRoleEnum(str, Enum):
    USER = "USER"      # Standard EV driver access
    ADMIN = "ADMIN"    # Full system administration
```

#### User Role Management

##### Automatic Role Assignment
```python
# Implementation: backend/routers/webhooks.py:15-45
@router.post("/clerk")
async def clerk_webhook(request: Request):
```

**Webhook Events**:
- **user.created**: Automatic USER role assignment for new registrations
- **user.updated**: Profile synchronization with Clerk data
- **user.deleted**: Account cleanup and data retention handling

##### Role-Based Route Protection
**Backend Routes**:
- `RequireAdmin` dependency: Admin-only endpoint protection
- `RequireAuth` dependency: General authentication requirement
- Route-level role validation with descriptive error messages

**Frontend Components**:
```typescript
// Implementation: frontend/components/RoleWrapper.tsx
export const AdminOnly = ({ children }) => {
export const UserOnly = ({ children }) => {
export const AuthenticatedOnly = ({ children }) => {
```

### Authentication Flow

#### User Registration & Login
1. **Registration**: Clerk handles user creation with email/phone verification
2. **Webhook Processing**: Backend receives user creation event
3. **Database Creation**: User record created with default USER role
4. **Wallet Initialization**: Empty wallet created for billing integration
5. **Session Establishment**: JWT token issued for API access

#### API Authentication
1. **Token Extraction**: Clerk session provides JWT token
2. **API Client Integration**: Automatic token injection in all API requests
3. **Backend Validation**: JWT signature and claims verification
4. **Role Authorization**: Endpoint-specific role requirement checking
5. **User Context**: Authenticated user information available in route handlers

#### Session Management
- **Token Refresh**: Automatic token renewal via Clerk SDK
- **Logout Handling**: Complete session cleanup across frontend and backend
- **Role Changes**: Real-time role updates via webhook system

---

## API Documentation

### REST API Architecture
**Base URL**: `http://localhost:8000` (development), production URL in environment  
**Authentication**: Bearer JWT tokens from Clerk  
**Content Type**: `application/json`  
**Error Format**: Standardized HTTP status codes with detailed JSON responses  

### Admin Management APIs

#### Station Management (`backend/routers/stations.py`)

##### List Stations
```http
GET /api/admin/stations
Authorization: Bearer {jwt_token}
Query Parameters:
  - page: int = 1
  - limit: int = 20
  - search: string (searches name, address)

Response:
{
  "data": [
    {
      "id": 1,
      "name": "Downtown Charging Hub",
      "latitude": 40.7128,
      "longitude": -74.0060,
      "address": "123 Main St, New York, NY",
      "created_at": "2025-01-15T10:30:00Z",
      "updated_at": "2025-01-15T10:30:00Z",
      "_charger_count": 4
    }
  ],
  "total": 1,
  "page": 1,
  "limit": 20
}
```

##### Create Station
```http
POST /api/admin/stations
Authorization: Bearer {jwt_token}
Content-Type: application/json

{
  "name": "New Charging Station",
  "latitude": 40.7589,
  "longitude": -73.9851,
  "address": "456 Broadway, New York, NY"
}

Response: 201 Created
{
  "id": 2,
  "name": "New Charging Station",
  "latitude": 40.7589,
  "longitude": -73.9851,
  "address": "456 Broadway, New York, NY",
  "created_at": "2025-01-22T14:20:00Z",
  "updated_at": "2025-01-22T14:20:00Z"
}
```

#### Charger Management (`backend/routers/chargers.py`)

##### List Chargers with Real-time Status
```http
GET /api/admin/chargers
Authorization: Bearer {jwt_token}
Query Parameters:
  - page: int = 1
  - limit: int = 20
  - status: ChargerStatusEnum
  - station_id: int
  - search: string (charge_point_string_id, name, serial_number)

Response:
{
  "data": [
    {
      "id": 1,
      "charge_point_string_id": "CP001",
      "name": "Fast Charger 1",
      "vendor": "ABB",
      "model": "Terra AC",
      "serial_number": "ABC123456",
      "latest_status": "Available",
      "last_heart_beat_time": "2025-01-22T14:15:00Z",
      "is_connected": true,
      "connection_status": "online",
      "station": {
        "id": 1,
        "name": "Downtown Charging Hub",
        "address": "123 Main St, New York, NY"
      },
      "connectors": [
        {
          "id": 1,
          "connector_id": 1,
          "connector_type": "Type2",
          "max_power_kw": 22.0
        }
      ]
    }
  ],
  "total": 1,
  "page": 1,
  "limit": 20
}
```

##### OCPP Remote Commands
```http
POST /api/admin/chargers/{charger_id}/remote-start
Authorization: Bearer {jwt_token}
Content-Type: application/json

{
  "id_tag": "user123",
  "connector_id": 1  // Optional - defaults to any available
}

Response: 200 OK
{
  "success": true,
  "message": "RemoteStartTransaction sent successfully",
  "ocpp_response": {
    "status": "Accepted"
  }
}
```

```http
POST /api/admin/chargers/{charger_id}/change-availability
Authorization: Bearer {jwt_token}
Content-Type: application/json

{
  "connector_id": 0,  // 0 = entire charge point
  "type": "Inoperative"  // or "Operative"
}

Response: 200 OK
{
  "success": true,
  "message": "ChangeAvailability sent successfully",
  "ocpp_response": {
    "status": "Accepted"
  }
}
```

#### Transaction Management (`backend/routers/transactions.py`)

##### List Transactions with Analytics
```http
GET /api/admin/transactions
Authorization: Bearer {jwt_token}
Query Parameters:
  - page: int = 1
  - limit: int = 20
  - status: TransactionStatusEnum
  - user_id: int
  - charger_id: int
  - start_date: string (ISO format)
  - end_date: string (ISO format)

Response:
{
  "data": [
    {
      "id": 1,
      "start_meter_kwh": 1250.5,
      "end_meter_kwh": 1275.8,
      "energy_consumed_kwh": 25.3,
      "start_time": "2025-01-22T10:00:00Z",
      "end_time": "2025-01-22T12:30:00Z",
      "transaction_status": "COMPLETED",
      "stop_reason": "Remote",
      "user": {
        "id": 1,
        "phone_number": "+1234567890",
        "full_name": "John Doe"
      },
      "charger": {
        "id": 1,
        "charge_point_string_id": "CP001",
        "name": "Fast Charger 1"
      },
      "vehicle": {
        "id": 1,
        "make": "Tesla",
        "model": "Model 3"
      }
    }
  ],
  "total": 1,
  "page": 1,
  "limit": 20,
  "summary": {
    "total_energy_kwh": 25.3,
    "active_sessions": 0,
    "completed_sessions": 1,
    "failed_sessions": 0
  }
}
```

##### Transaction Meter Values
```http
GET /api/admin/transactions/{transaction_id}/meter-values
Authorization: Bearer {jwt_token}

Response:
{
  "transaction_id": 1,
  "meter_values": [
    {
      "id": 1,
      "reading_kwh": 1251.2,
      "current": 16.5,
      "voltage": 230.0,
      "power_kw": 3.8,
      "created_at": "2025-01-22T10:05:00Z"
    }
  ],
  "chart_data": {
    "energy": [1251.2, 1252.4, 1253.8],
    "power": [3.8, 3.7, 3.9],
    "timestamps": ["2025-01-22T10:05:00Z", "2025-01-22T10:10:00Z", "2025-01-22T10:15:00Z"]
  }
}
```

#### User Management (`backend/routers/users.py`)

##### List Users with Wallet Information
```http
GET /users
Authorization: Bearer {jwt_token}
Query Parameters:
  - page: int = 1
  - limit: int = 20
  - role: UserRoleEnum

Response:
{
  "data": [
    {
      "id": 1,
      "clerk_user_id": "user_123",
      "full_name": "John Doe",
      "email": "john@example.com",
      "phone_number": "+1234567890",
      "role": "USER",
      "is_active": true,
      "wallet": {
        "balance": 150.75,
        "currency": "INR"
      },
      "created_at": "2025-01-15T08:30:00Z"
    }
  ],
  "total": 1,
  "page": 1,
  "limit": 20
}
```

##### **NEW**: User Transaction History
```http
GET /users/{id}/transactions
Authorization: Bearer {jwt_token}
Query Parameters:
  - page: int = 1
  - limit: int = 10
  - status: TransactionStatusEnum (optional)

Response:
{
  "data": [
    {
      "id": 1,
      "start_time": "2025-01-22T10:00:00Z",
      "end_time": "2025-01-22T12:30:00Z",
      "energy_consumed_kwh": 25.3,
      "transaction_status": "COMPLETED",
      "charger": {
        "id": 1,
        "charge_point_string_id": "CP001",
        "name": "Fast Charger 1"
      }
    }
  ],
  "total": 15,
  "page": 1,
  "limit": 10
}
```

##### **NEW**: User Wallet Transaction History
```http
GET /users/{id}/wallet-transactions
Authorization: Bearer {jwt_token}
Query Parameters:
  - page: int = 1
  - limit: int = 15

Response:
{
  "data": [
    {
      "id": 1,
      "amount": -25.30,
      "type": "CHARGE_DEDUCT",
      "description": "Charging session at CP001",
      "payment_metadata": {"transaction_id": 123},
      "created_at": "2025-01-22T12:30:00Z",
      "running_balance": 124.70
    },
    {
      "id": 2,
      "amount": 150.00,
      "type": "TOP_UP",
      "description": "Wallet top-up",
      "created_at": "2025-01-22T08:00:00Z",
      "running_balance": 150.00
    }
  ],
  "wallet_balance": 124.70,
  "total": 2,
  "page": 1,
  "limit": 15
}
```

##### **NEW**: Transaction Summary Statistics
```http
GET /users/{id}/transactions-summary
Authorization: Bearer {jwt_token}

Response:
{
  "total_transactions": 15,
  "completed_transactions": 12,
  "failed_transactions": 1,
  "total_energy_kwh": 378.5,
  "total_spent": 1892.50,
  "currency": "INR"
}
```

#### Firmware Management (`backend/routers/firmware.py`)

##### Upload Firmware File
```http
POST /api/admin/firmware/upload
Authorization: Bearer {jwt_token}
Content-Type: multipart/form-data

FormData:
  - file: File (.bin, .hex, .fw)
  - version: string (required, unique)
  - description: string (optional, release notes)

Response: 200 OK
{
  "id": 1,
  "version": "1.0.0",
  "filename": "1.0.0_simple_ota.bin",
  "file_size": 912160,
  "checksum": "d0fd2e471c76287adab65cba424630fa",
  "description": "Initial firmware release",
  "uploaded_by_id": 1,
  "created_at": "2025-01-22T10:00:00Z",
  "is_active": true
}
```

##### List Firmware Files
```http
GET /api/admin/firmware
Authorization: Bearer {jwt_token}
Query Parameters:
  - page: int = 1
  - limit: int = 20
  - is_active: bool = true

Response:
{
  "data": [
    {
      "id": 1,
      "version": "1.0.0",
      "filename": "1.0.0_simple_ota.bin",
      "file_size": 912160,
      "checksum": "d0fd2e471c76287...",
      "description": "Initial firmware release",
      "uploaded_by_id": 1,
      "created_at": "2025-01-22T10:00:00Z",
      "is_active": true
    }
  ],
  "total": 1,
  "page": 1,
  "limit": 20
}
```

##### Trigger Firmware Update (Single Charger)
```http
POST /api/admin/firmware/chargers/{charger_id}/update
Authorization: Bearer {jwt_token}
Content-Type: application/json

{
  "firmware_file_id": 1
}

Response: 200 OK
{
  "id": 1,
  "charger_id": 5,
  "firmware_file_id": 1,
  "status": "PENDING",
  "download_url": "https://lyncpower.com/firmware/1.0.0_simple_ota.bin",
  "initiated_at": "2025-01-22T14:00:00Z",
  "started_at": null,
  "completed_at": null,
  "error_message": null
}

Errors:
  - 400: Charger offline, active transaction, or same version
  - 404: Charger or firmware not found
  - 500: OCPP command failed
```

##### Bulk Firmware Update
```http
POST /api/admin/firmware/bulk-update
Authorization: Bearer {jwt_token}
Content-Type: application/json

{
  "firmware_file_id": 1,
  "charger_ids": [1, 2, 3, 4, 5]
}

Response: 200 OK
{
  "success": [
    {
      "charger_id": 1,
      "charger_name": "CP001",
      "update_id": 1
    },
    {
      "charger_id": 2,
      "charger_name": "CP002",
      "update_id": 2
    }
  ],
  "failed": [
    {
      "charger_id": 3,
      "charger_name": "CP003",
      "reason": "Charger is offline"
    },
    {
      "charger_id": 4,
      "charger_name": "CP004",
      "reason": "Charger has an active charging session"
    }
  ]
}
```

##### Get Firmware Update History
```http
GET /api/admin/firmware/chargers/{charger_id}/history
Authorization: Bearer {jwt_token}
Query Parameters:
  - page: int = 1
  - limit: int = 10

Response:
{
  "data": [
    {
      "id": 1,
      "charger_id": 5,
      "firmware_file_id": 1,
      "status": "INSTALLED",
      "download_url": "https://lyncpower.com/firmware/1.0.0_simple_ota.bin",
      "initiated_at": "2025-01-22T14:00:00Z",
      "started_at": "2025-01-22T14:01:00Z",
      "completed_at": "2025-01-22T14:05:30Z",
      "error_message": null
    }
  ],
  "total": 1,
  "page": 1,
  "limit": 10
}
```

##### Get Firmware Update Dashboard Status
```http
GET /api/admin/firmware/updates/status
Authorization: Bearer {jwt_token}

Response:
{
  "in_progress": [
    {
      "update_id": 2,
      "charger_id": 6,
      "charger_name": "Fast Charger 2",
      "charge_point_id": "CP002",
      "firmware_version": "1.0.0",
      "status": "DOWNLOADING",
      "started_at": "2025-01-22T15:00:00Z",
      "initiated_at": "2025-01-22T14:59:00Z"
    }
  ],
  "summary": {
    "pending": 3,
    "downloading": 1,
    "installing": 0,
    "completed_today": 5,
    "failed_today": 1
  }
}
```

##### **NEW**: Get Latest Firmware (Public API)
```http
GET /api/firmware/latest
No Authentication Required

Response: 200 OK
{
  "version": "1.0.0",
  "filename": "1.0.0_simple_ota.bin",
  "download_url": "https://lyncpower.com/firmware/1.0.0_simple_ota.bin",
  "checksum": "d0fd2e471c76287adab65cba424630fa",
  "file_size": 912160
}

Response: 404 Not Found
{
  "detail": "No firmware files available"
}
```

**Use Case**: Non-OCPP charge points can poll this endpoint to discover firmware updates.

**Integration Example**:
```c
// ESP32 Example
void checkForFirmwareUpdate() {
    HTTPClient http;
    http.begin("https://lyncpower.com/api/firmware/latest");

    if (http.GET() == 200) {
        // Parse JSON and compare version
        // Download from download_url
        // Verify checksum
        // Install and reboot
    }
}
```

**Documentation**: See `/backend/docs/FIRMWARE_API.md` for comprehensive integration guide

#### Signal Quality Monitoring (`backend/routers/chargers.py`)

##### Get Signal Quality History
```http
GET /api/admin/chargers/{charger_id}/signal-quality
Authorization: Bearer {jwt_token}
Query Parameters:
  - page: int = 1
  - limit: int = 20 (max 100)
  - hours: int = 24 (max 720 for 30 days)

Response: 200 OK
{
  "data": [
    {
      "id": 1,
      "charger_id": 5,
      "rssi": 22,  // Received Signal Strength Indicator
      "ber": 99,   // Bit Error Rate
      "timestamp": "86",
      "created_at": "2025-01-22T14:00:00Z"
    }
  ],
  "total": 50,
  "page": 1,
  "limit": 20,
  "charger_id": 5,
  "latest_rssi": 22,
  "latest_ber": 99
}
```

**Signal Strength Interpretation**:
- **Good**: RSSI ≥ 10 (green badge)
- **Fair**: RSSI 5-9 (yellow badge)
- **Poor**: RSSI 0-4 (red badge)
- **Unknown**: RSSI = 99 or null (gray badge)

##### Get Latest Signal Quality
```http
GET /api/admin/chargers/{charger_id}/signal-quality/latest
Authorization: Bearer {jwt_token}

Response: 200 OK
{
  "id": 50,
  "charger_id": 5,
  "rssi": 22,
  "ber": 99,
  "timestamp": "86",
  "created_at": "2025-01-22T15:00:00Z"
}

Response: 200 OK (no data)
null
```

**Use Cases**:
- Real-time signal strength monitoring on charger detail page
- Historical signal quality analysis
- Connectivity troubleshooting for remote charge points

**Data Retention**: Signal quality data older than 90 days is automatically cleaned up by the data retention service

### Legacy OCPP APIs (Backward Compatibility)
**Location**: `backend/main.py:657-725`

```http
GET /api/charge-points          # List connected charge points
POST /api/charge-points/{id}/request  # Send OCPP command
GET /api/logs                   # Get OCPP message logs
GET /api/logs/{charge_point_id} # Get logs for specific charger
```

### Error Handling Standards
All API endpoints use standardized error responses:

```json
{
  "detail": "Charger with ID 999 not found",
  "status_code": 404,
  "error_type": "NOT_FOUND",
  "timestamp": "2025-01-22T14:30:00Z",
  "path": "/api/admin/chargers/999"
}
```

**HTTP Status Codes**:
- `200`: Success with data
- `201`: Resource created successfully
- `400`: Bad Request (validation error)
- `401`: Unauthorized (authentication required)
- `403`: Forbidden (insufficient permissions)
- `404`: Resource not found
- `409`: Conflict (duplicate resource)
- `422`: Validation Error (detailed field errors)
- `500`: Internal Server Error

---

## Real-Time Features

### Connection State Management
**Architecture**: Redis-backed real-time state with database persistence

#### Redis Connection Manager (`backend/redis_manager.py`)
```python
class RedisConnectionManager:
    async def add_connected_charger(self, charger_id: str, connection_data: Dict):
        """Add charger to active connection registry"""
        
    async def is_charger_connected(self, charger_id: str) -> bool:
        """Check if charger is currently connected"""
        
    async def get_all_connected_chargers(self) -> List[str]:
        """Get list of all connected charger IDs"""
```

**Features**:
- **Connection Tracking**: Real-time charger connection state
- **Bulk Status Queries**: Dashboard-optimized bulk connection checks
- **Graceful Degradation**: Fallback to in-memory state when Redis unavailable
- **Automatic Cleanup**: Dead connection detection and removal

#### Connection Monitoring
**Implementation**: `backend/main.py:510-573`

**Monitoring Strategy**:
- **Heartbeat Timeout**: 90 seconds (2x OCPP heartbeat interval)
- **Check Frequency**: Every 30 seconds per connection
- **Cleanup Trigger**: 300 seconds without heartbeat for periodic cleanup
- **Recovery Handling**: Automatic reconnection support

### Frontend Real-Time Updates

#### Dashboard Polling Strategy (`frontend/lib/queries/dashboard.ts`)
```typescript
const useDashboardStats = () => {
  return useQuery({
    queryKey: ['dashboard-stats'],
    queryFn: fetchDashboardStats,
    refetchInterval: 10000,      // 10 seconds
    staleTime: 30000,            // 30 seconds stale time
    cacheTime: 300000,           // 5 minutes cache
  });
};
```

#### Charger Status Monitoring (`frontend/lib/queries/chargers.ts`)
```typescript
const useChargers = (options = {}) => {
  return useQuery({
    queryKey: ['chargers'],
    queryFn: fetchChargers,
    refetchInterval: 10000,      // Real-time status updates
    staleTime: 5000,             // 5 seconds stale time for dynamic data
    select: (data) => ({
      ...data,
      data: data.data.map(charger => ({
        ...charger,
        status_color: getStatusColor(charger.latest_status),
        connection_indicator: charger.is_connected ? 'online' : 'offline'
      }))
    })
  });
};
```

### Optimistic UI Updates
**Pattern**: Immediate feedback with rollback capability

#### Example: Availability Toggle (`frontend/lib/queries/chargers.ts`)
```typescript
const useChangeAvailability = () => {
  return useMutation({
    mutationFn: ({ chargerId, type }) => 
      chargerService.changeAvailability(chargerId, { connector_id: 0, type }),
    
    onMutate: async ({ chargerId, type }) => {
      // Cancel outgoing refetches
      await queryClient.cancelQueries({ queryKey: ['chargers'] });
      
      // Snapshot current state
      const previousChargers = queryClient.getQueryData(['chargers']);
      
      // Optimistically update UI
      queryClient.setQueryData(['chargers'], (old) => ({
        ...old,
        data: old.data.map(charger => 
          charger.id === chargerId 
            ? { 
                ...charger, 
                latest_status: type === 'Operative' ? 'Available' : 'Unavailable',
                is_updating: true  // Loading indicator
              }
            : charger
        )
      }));
      
      return { previousChargers };
    },
    
    onError: (err, variables, context) => {
      // Rollback on error
      queryClient.setQueryData(['chargers'], context.previousChargers);
      toast.error('Failed to change charger availability');
    },
    
    onSettled: () => {
      // Refresh data regardless of success/error
      queryClient.invalidateQueries({ queryKey: ['chargers'] });
    },
    
    onSuccess: () => {
      toast.success('Charger availability updated successfully');
    }
  });
};
```

### WebSocket Integration Architecture

#### OCPP WebSocket Flow
1. **Charger Connection**: WebSocket connection to `/ocpp/{charge_point_id}`
2. **Authentication**: Database validation of charge_point_string_id
3. **Message Logging**: Complete OCPP message audit trail with correlation IDs
4. **State Updates**: Real-time database and Redis state updates
5. **Frontend Sync**: TanStack Query polling picks up changes within 10 seconds

#### Message Correlation System (`backend/main.py:401-445`)
```python
class LoggingWebSocketAdapter:
    async def recv(self):
        msg = await super().recv()
        correlation_id = self.extract_correlation_id(msg)
        await log_message(
            charger_id=self.charge_point_id,
            direction="IN",
            message_type="OCPP",
            payload=msg,
            correlation_id=correlation_id
        )
        return msg
    
    async def send(self, data):
        correlation_id = self.extract_correlation_id(data)
        await log_message(
            charger_id=self.charge_point_id,
            direction="OUT",
            message_type="OCPP",
            payload=data,
            correlation_id=correlation_id
        )
        await super().send(data)
```

### Performance Optimization

#### Query Optimization Strategy
**Stale Time Configuration** (by data volatility):
- **Static Data** (Stations): 2 minutes stale time
- **Dynamic Data** (Chargers): 10 seconds stale time
- **Real-time Data** (Active Transactions): 5 seconds stale time

#### Caching Strategy
- **Frontend**: TanStack Query with intelligent cache invalidation
- **Backend**: Redis for connection state, PostgreSQL for persistent data
- **API Responses**: Optimized serialization with prefetch relationships

---

## User Experience Features

### Interactive Station Discovery

#### Station Finder with Maps (`frontend/app/stations/page.tsx`)
**Technology**: React Leaflet integration
**Features**:
- **Interactive Mapping**: Real-time station location display
- **Status Indicators**: Live availability status from OCPP data
- **Distance Calculation**: GPS-based proximity sorting
- **Search & Filtering**: Name and location-based filtering
- **Mobile Responsive**: Touch-optimized map controls

#### Station Map Component (`frontend/app/stations/StationMap.tsx`)
```typescript
// Key features implementation
const StationMap = ({ stations, userLocation }) => {
  return (
    <MapContainer center={userLocation || defaultCenter} zoom={13}>
      <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
      {stations.map(station => (
        <Marker 
          key={station.id}
          position={[station.latitude, station.longitude]}
          icon={getStatusIcon(station.availability)}
        >
          <Popup>
            <StationPopup station={station} />
          </Popup>
        </Marker>
      ))}
    </MapContainer>
  );
};
```

**Map Features**:
- **Real-time Markers**: Station status-based marker colors
- **Information Popups**: Detailed station information and actions
- **User Location**: GPS-based current location display
- **Routing Integration**: Direction links to external navigation apps

### QR Code Scanning System

#### QR Scanner Component (`frontend/app/scanner/page.tsx`)
**Technology**: ZXing library for barcode detection
**Implementation**: `frontend/components/QRScanner.tsx`

```typescript
const QRScanner = ({ onScan, onError }) => {
  const [isActive, setIsActive] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  
  useEffect(() => {
    if (isActive) {
      const codeReader = new BrowserQRCodeReader();
      codeReader.decodeFromVideoDevice(null, videoRef.current)
        .then(result => {
          onScan(result.getText());
        })
        .catch(onError);
    }
  }, [isActive]);
};
```

**Features**:
- **Camera Integration**: Real-time video feed processing
- **QR Code Detection**: Automatic barcode recognition
- **Error Handling**: Invalid code and camera permission errors
- **Direct Navigation**: Automatic redirect to charger interface
- **Mobile Optimization**: Touch-optimized scanning interface

### Role-Based User Interface

#### Adaptive Dashboard (`frontend/app/page.tsx`)
**Pattern**: Role-based component rendering

**User Dashboard Features**:
- **Quick Actions**: Station finder and QR scanner shortcuts
- **Recent Sessions**: Personal charging history summary
- **Wallet Status**: Current balance and recent transactions
- **Station Favorites**: Bookmarked charging locations

**Admin Dashboard Features**:
- **System Overview**: Real-time statistics and alerts
- **Connection Monitor**: Live charger connection status
- **Recent Transactions**: System-wide transaction activity
- **Quick Management**: Direct access to admin functions

#### Navigation Adaptation (`frontend/components/Navbar.tsx`)
```typescript
const Navbar = () => {
  const { user } = useUser();
  const userRole = user?.publicMetadata?.role;
  
  return (
    <nav>
      {/* Common navigation items */}
      <NavItem href="/">Dashboard</NavItem>
      
      {/* Role-specific navigation */}
      {userRole === 'USER' && (
        <>
          <NavItem href="/stations">Find Stations</NavItem>
          <NavItem href="/scanner">QR Scanner</NavItem>
        </>
      )}
      
      {userRole === 'ADMIN' && (
        <>
          <NavItem href="/admin/stations">Manage Stations</NavItem>
          <NavItem href="/admin/chargers">Manage Chargers</NavItem>
          <NavItem href="/admin/users">Manage Users</NavItem>
        </>
      )}
    </nav>
  );
};
```

### Mobile-Responsive Design

#### Responsive Framework
**Technology**: Tailwind CSS v4 with mobile-first approach
**Breakpoints**: 
- `sm`: 640px (Mobile landscape)
- `md`: 768px (Tablet)
- `lg`: 1024px (Desktop)
- `xl`: 1280px (Large desktop)

#### Mobile Optimizations
- **Touch Targets**: Minimum 44px tap targets for mobile interaction
- **Gesture Support**: Swipe navigation for mobile table interfaces
- **Responsive Tables**: Horizontal scroll with sticky columns
- **Mobile Map Controls**: Touch-optimized zoom and pan controls
- **Camera Integration**: Native camera API integration for QR scanning

### Progressive Web App Features

#### PWA Configuration (`frontend/next.config.ts`)
```typescript
const nextConfig = {
  // PWA manifest generation
  experimental: {
    appDir: true,
  },
  // Service worker for offline capability
};
```

**PWA Features**:
- **App Manifest**: Native app-like installation
- **Offline Support**: Critical functionality available offline
- **Push Notifications**: Real-time charging status updates (future)
- **Background Sync**: Automatic data synchronization when online

---

## Docker Deployment & Infrastructure

### Docker Compose Architecture
The system is deployed as a multi-container Docker application on AWS EC2, with separate production and staging environments:

- **Production**: `app.voltlync.com` — EC2 t3.medium, `deploy` branch, `docker-compose.prod.yml` + `.env.prod`
- **Staging**: `staging.voltlync.com` — EC2 t3.medium (cloned from production AMI), `develop` branch, `docker-compose.staging.yml` + `.env.staging`
- **Shared keys**: Both environments use the same Clerk app and Razorpay live keys (QR payments require live mode)

```
┌────────────────────────────────────────────────────────────────┐
│  AWS EC2 Instance (app.voltlync.com)                           │
│                                                                 │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   │
│  │  Nginx   │──►│ Backend  │──►│PostgreSQL│   │  Redis   │   │
│  │  (SSL)   │   │ (FastAPI)│──►│  (DB)    │   │  (Cache) │   │
│  │  :80/443 │   │  :8000   │   │  :5432   │   │  :6379   │   │
│  └──────────┘   └──────────┘   └──────────┘   └──────────┘   │
│       │              │                                          │
│       │         ┌──────────┐                                   │
│       └────────►│ Frontend │                                   │
│                 │ (Next.js)│                                   │
│                 │  :3000   │                                   │
│                 └──────────┘                                   │
└────────────────────────────────────────────────────────────────┘
```

### Container Configuration

**Backend** (`backend/Dockerfile`):
- Multi-stage build with Python 3.11
- Runs migrations on startup via `docker-entrypoint.sh`
- Health check: `curl http://localhost:8000/health`
- Environment: DATABASE_URL, REDIS_URL, Clerk keys, Razorpay keys, QR payment config

**Frontend** (`frontend/Dockerfile`):
- Multi-stage Next.js build with standalone output
- Node.js 18 Alpine runtime
- Environment: NEXT_PUBLIC_API_URL, NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY

**Nginx** (`nginx/`):
- SSL termination with Let's Encrypt certificates
- WebSocket proxying for `/ocpp/` path
- Rate limiting and security headers
- Separate configs: `default.conf` (dev), `staging.conf`, `prod.conf`
- Static file caching for firmware downloads

**PostgreSQL**:
- Persistent volume for data
- Automatic backup support

**Redis**:
- `--maxmemory 256mb --maxmemory-policy allkeys-lru`
- Used for: charger connection state, QR session budget cache

### Docker Compose Files
- `docker-compose.yml` - Local development
- `docker-compose.staging.yml` - Staging environment
- `docker-compose.prod.yml` - Production environment

### Makefile Targets
Key deployment and management commands:
```bash
# Production (app.voltlync.com, branch: deploy)
make prod-push        # Push current branch to origin/deploy
make prod-deploy      # Pull + rebuild on EC2
make prod-up          # Start production stack
make prod-down        # Stop production stack
make prod-migrate     # Run database migrations in container
make prod-logs        # Tail all container logs

# Staging (staging.voltlync.com, branch: develop)
make staging-push     # Push current branch to origin/develop
make staging-deploy   # Pull + rebuild on staging EC2
make staging-up       # Start staging stack
make staging-down     # Stop staging stack
make staging-migrate  # Run staging database migrations
make staging-logs     # Tail staging container logs

# Development
make docker-build     # Build all images
make seed             # Seed dev DB (users, stations, chargers, franchisees)
                      # Pass CLERK_ADMIN_ID=user_xxx ADMIN_EMAIL=you@... to seed yourself as admin
                      # `make docker-seed` is kept as an alias
```

### Environment Configuration
Separate `.env` files for each environment:
- `.env.docker.example` - Local Docker development
- `.env.staging.example` - Staging
- `.env.prod.example` - Production (includes Razorpay, Sentry, New Relic keys)

### Monitoring Stack
- **Sentry**: Error tracking with ASGI middleware integration
- **New Relic**: APM with custom transaction tracing (`@trace_transaction` decorator)
- **Structured Logging**: Timestamp-prefixed logs with correlation IDs
- **Health Check**: `GET /health` endpoint for container orchestration

---

## Security & Compliance

### Authentication Security

#### Clerk Integration Security
**JWT Validation**: Industry-standard JWT token verification
**Token Security**:
- Short-lived access tokens (1 hour)
- Automatic token refresh
- Secure token storage in HTTP-only cookies

#### API Security
**Authorization Headers**: Bearer token authentication for all protected routes
**Role Validation**: Server-side role verification for admin endpoints
**Request Validation**: Pydantic schema validation for all API inputs

### OCPP Security Considerations

#### Connection Security
**Charger Registration**: Only pre-registered chargers can establish OCPP connections
**Connection Validation**: Database verification before WebSocket handshake
**Duplicate Prevention**: Single active connection per charge point ID
**Automatic Cleanup**: Dead connection detection and removal

#### Message Security
**Complete Audit Trail**: All OCPP messages logged with timestamps and correlation IDs
**Message Validation**: OCPP protocol compliance validation
**Error Handling**: Secure error responses without information leakage

### Data Protection

#### Database Security
**SQL Injection Prevention**: Parameterized queries via Tortoise ORM
**Connection Security**: SSL-encrypted database connections in production
**Data Encryption**: Sensitive data encrypted at rest
**Access Control**: Role-based database access restrictions

#### Privacy Protection
**User Data Minimization**: Only essential user data collected
**Data Anonymization**: Transaction data can be anonymized for analytics
**GDPR Compliance**: User data deletion capabilities
**Secure Storage**: Encrypted storage of sensitive information

### Network Security

#### CORS Configuration
```python
# Implementation: backend/main.py
ALLOWED_ORIGINS = [
    "http://localhost:3000",           # Local development - Next.js
    "http://localhost:5173",           # Local development - Vite (mobile app)
    "http://frontend:3000",            # Docker internal network
    "https://powerlync.com",           # Production frontend
    "https://www.powerlync.com",       # Production frontend (www)
    "https://lyncpower.com",           # Backend domain
    "https://www.lyncpower.com",       # Backend domain (www)
]
# Explicit allow_methods and allow_headers (not wildcard)
# Custom OptionsMiddleware handles CORS preflight to avoid auth middleware conflicts
```

#### Environment Security
**Credential Management**: All sensitive configuration via environment variables
**Secret Rotation**: Support for credential rotation without service interruption
**Production Configuration**: Separate configuration for development and production

### OCPP 1.6 Compliance

#### Core Profile Implementation
**Message Support**:
✅ `BootNotification`: Charger registration and configuration  
✅ `Heartbeat`: Connection liveness monitoring  
✅ `StatusNotification`: Charger status updates  
✅ `StartTransaction`: Transaction initiation  
✅ `StopTransaction`: Transaction completion  
✅ `MeterValues`: Real-time energy data  
✅ `RemoteStartTransaction`: Remote charging initiation  
✅ `RemoteStopTransaction`: Remote charging termination  
✅ `ChangeAvailability`: Remote availability control  

#### Protocol Compliance
**Message Format**: OCPP-compliant JSON message structure
**Status Values**: Complete OCPP 1.6 charge point status support
**Error Codes**: OCPP-standard error code handling
**Timestamps**: ISO 8601 format with timezone information

#### Standards Documentation
**Compliance Logging**: Complete message audit trail for certification
**Protocol Testing**: Comprehensive test suite for OCPP message handling
**Certification Ready**: Implementation ready for OCPP certification testing

---

## Testing Framework

### Testing Architecture
**Location**: `backend/tests/`
**Framework**: pytest with async support and comprehensive fixtures

### Test Categories

#### Unit Tests (`backend/tests/test_*.py`)
**Purpose**: Fast, isolated component testing
**Execution**: `pytest -m unit` (~1 second total)

**Database Model Tests**:
```python
# Example: backend/tests/test_models.py
@pytest.mark.asyncio
async def test_charger_creation():
    """Test charger model creation with OCPP compliance"""
    station = await ChargingStation.create(name="Test Station")
    charger = await Charger.create(
        charge_point_string_id="TEST001",
        station=station,
        name="Test Charger",
        latest_status=ChargerStatusEnum.AVAILABLE
    )
    assert charger.charge_point_string_id == "TEST001"
    assert charger.latest_status == ChargerStatusEnum.AVAILABLE
```

**API Endpoint Tests**:
```python
# Example: backend/tests/test_stations.py
@pytest.mark.asyncio
async def test_create_station_endpoint():
    """Test station creation via admin API"""
    station_data = {
        "name": "New Station",
        "latitude": 40.7128,
        "longitude": -74.0060,
        "address": "123 Test St"
    }
    response = await client.post("/api/admin/stations", json=station_data)
    assert response.status_code == 201
    assert response.json()["name"] == "New Station"
```

#### Integration Tests (`backend/tests/test_integration.py`)
**Purpose**: Complete OCPP workflow testing with real WebSocket connections
**Execution**: `pytest -m integration` (~45 seconds total)

**Complete Charging Session Test**:
```python
@pytest.mark.asyncio
async def test_complete_charging_session():
    """Test full OCPP transaction lifecycle"""
    
    async with websockets.connect(f"ws://localhost:8000/ocpp/{CHARGE_POINT_ID}") as ws:
        
        # 1. BootNotification
        boot_msg = [2, "1", "BootNotification", {
            "chargePointVendor": "Test", 
            "chargePointModel": "TestModel"
        }]
        await ws.send(json.dumps(boot_msg))
        response = json.loads(await ws.recv())
        assert response[2]["status"] == "Accepted"
        
        # 2. StartTransaction
        start_msg = [2, "2", "StartTransaction", {
            "connectorId": 1,
            "idTag": "test_user",
            "meterStart": 1000,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }]
        await ws.send(json.dumps(start_msg))
        response = json.loads(await ws.recv())
        transaction_id = response[2]["transactionId"]
        assert transaction_id > 0
        
        # 3. MeterValues
        meter_msg = [2, "3", "MeterValues", {
            "connectorId": 1,
            "transactionId": transaction_id,
            "meterValue": [{
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "sampledValue": [{
                    "value": "1500",
                    "measurand": "Energy.Active.Import.Register",
                    "unit": "Wh"
                }]
            }]
        }]
        await ws.send(json.dumps(meter_msg))
        
        # 4. StopTransaction
        stop_msg = [2, "4", "StopTransaction", {
            "transactionId": transaction_id,
            "meterStop": 2000,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "reason": "Remote"
        }]
        await ws.send(json.dumps(stop_msg))
        response = json.loads(await ws.recv())
        assert response[2]["idTagInfo"]["status"] == "Accepted"
    
    # Verify transaction in database
    transaction = await Transaction.get(id=transaction_id)
    assert transaction.transaction_status == TransactionStatusEnum.COMPLETED
    assert transaction.energy_consumed_kwh == 1.0  # (2000-1000)/1000
```

#### Infrastructure Tests (`backend/tests/test_infrastructure.py`)
**Purpose**: External dependency testing (database, Redis, Clerk)
**Execution**: `pytest -m infrastructure` (~5 seconds total)

```python
@pytest.mark.asyncio
async def test_database_connection():
    """Test database connectivity and basic operations"""
    await init_db()
    
    # Test CRUD operations
    station = await ChargingStation.create(name="Test Infrastructure Station")
    assert station.id is not None
    
    retrieved = await ChargingStation.get(id=station.id)
    assert retrieved.name == "Test Infrastructure Station"

@pytest.mark.asyncio
async def test_redis_connection():
    """Test Redis connectivity and operations"""
    await redis_manager.connect()
    
    # Test connection tracking
    test_data = {"connected_at": datetime.now()}
    await redis_manager.add_connected_charger("TEST_CP", test_data)
    is_connected = await redis_manager.is_charger_connected("TEST_CP")
    assert is_connected is True
```

### OCPP Simulators (`backend/simulators/`)

#### Full Success Simulator (`backend/simulators/ocpp_simulator_full_success.py`)
**Purpose**: Complete OCPP charger simulation for testing

```python
class OCPPChargerSimulator:
    """Complete OCPP 1.6 charger simulation"""
    
    async def simulate_charging_session(self):
        """Simulate complete charging session"""
        
        # 1. Connect and boot
        await self.connect()
        await self.send_boot_notification()
        
        # 2. Send status available
        await self.send_status_notification("Available")
        
        # 3. Start transaction
        transaction_id = await self.send_start_transaction()
        
        # 4. Send periodic meter values
        for i in range(10):
            await self.send_meter_values(1000 + i * 100, transaction_id)
            await asyncio.sleep(30)  # 30-second intervals
        
        # 5. Stop transaction
        await self.send_stop_transaction(transaction_id)
        
        # 6. Send status available
        await self.send_status_notification("Available")
```

#### Availability Testing (`backend/simulators/ocpp_simulator_change_availability.py`)
**Purpose**: Test ChangeAvailability command handling

```python
async def test_availability_changes():
    """Test ChangeAvailability command handling"""
    
    simulator = OCPPChargerSimulator()
    await simulator.connect()
    await simulator.send_boot_notification()
    
    # Listen for ChangeAvailability commands
    while True:
        message = await simulator.websocket.recv()
        parsed = json.loads(message)
        
        if parsed[2] == "ChangeAvailability":
            # Respond with acceptance
            response = [3, parsed[1], {"status": "Accepted"}]
            await simulator.websocket.send(json.dumps(response))
            
            # Update status accordingly
            new_status = "Unavailable" if parsed[3]["type"] == "Inoperative" else "Available"
            await simulator.send_status_notification(new_status)
```

#### Disconnect/Power Failure Simulator (`backend/simulators/ocpp_simulator_disconnect.py`)
**Purpose**: Synchronous websocket-based simulator for testing charger disconnect and transaction suspend/resume scenarios

**Architecture**: Uses the `websocket-client` library (synchronous) rather than `websockets` (async) for simpler sequential test flows. Manages message routing between client CALLs and server-initiated CALLs (RemoteStartTransaction, DataTransfer).

**Test Modes**:

| Mode | Flag | Behavior | Expected Outcome |
|------|------|----------|-----------------|
| No Reconnect | `--test-no-reconnect` | Disconnects mid-charge, never reconnects | Transaction: SUSPENDED -> STOPPED after ~180s timeout |
| Reconnect | `--test-reconnect` | Disconnects mid-charge, reconnects after `--reconnect-delay` seconds | Transaction: SUSPENDED -> timeout reset on BootNotification -> PostBootState -> resume charging |
| No Transaction | `--test-no-transaction` | Disconnects with no active transaction | Clean disconnect, no transaction changes |

**Reconnect Flow**:
1. Connects, sends BootNotification, waits for RemoteStartTransaction from server
2. Charges for 30s with periodic MeterValues and Heartbeats
3. Kills TCP connection (simulates power failure -- no WebSocket close frame)
4. Waits `--reconnect-delay` seconds, then reconnects
5. Sends BootNotification, receives PostBootState DataTransfer
6. Parses `hasPendingTransaction` from PostBootState
7. If pending: resumes charging with Preparing -> Charging -> MeterValues -> StopTransaction
8. If not pending (timeout already expired): sends Available status

**Key Implementation Details**:
- `disconnect_hard()`: Closes raw TCP socket without WebSocket close frame to simulate power failure
- `_wait_for_remote_start()`: Polls for server-initiated RemoteStartTransaction, sending heartbeats while waiting
- `_pending_server_calls`: Queue for server CALLs that arrive while waiting for a CALLRESULT
- PostBootState parsing: Reads `hasPendingTransaction`, `transactionId`, and `lastMeterValueWh` to resume from correct meter reading

**Usage**:
```bash
# Never reconnect (test full timeout flow)
python ocpp_simulator_disconnect.py --charger-id <id> --test-no-reconnect

# Reconnect within timeout window (60s)
python ocpp_simulator_disconnect.py --charger-id <id> --test-reconnect --reconnect-delay 60

# Reconnect after timeout expires (200s > 180s disconnect timeout)
python ocpp_simulator_disconnect.py --charger-id <id> --test-reconnect --reconnect-delay 200

# Disconnect with no active transaction
python ocpp_simulator_disconnect.py --charger-id <id> --test-no-transaction

# Against production
python ocpp_simulator_disconnect.py --charger-id <id> --server wss://app.voltlync.com --test-reconnect
```

### Test Configuration & Execution

#### Pytest Configuration (`backend/pyproject.toml`)
```toml
[tool.pytest.ini_options]
markers = [
    "unit: Unit tests (fast, no external dependencies)",
    "integration: Integration tests (requires running server)",
    "infrastructure: Infrastructure tests (requires Redis and database)",
    "slow: Slow tests that take more than 30 seconds"
]
asyncio_mode = "auto"
testpaths = ["tests"]
```

#### Test Execution Commands
```bash
# Run all tests
pytest

# Run by category
pytest -m unit          # Fast unit tests
pytest -m integration   # Full OCPP WebSocket tests
pytest -m infrastructure # Database/Redis tests

# Run with coverage
pytest --cov=. --cov-report=html

# Watch mode for development
python watch_and_test.py
```

#### Test Environment Setup (`backend/tests/conftest.py`)
```python
@pytest.fixture
async def setup_test_environment():
    """Set up clean test environment with test data"""
    
    # Initialize test database
    await init_db()
    
    # Create test station and charger
    station = await ChargingStation.create(
        name="Test Station",
        latitude=40.7128,
        longitude=-74.0060,
        address="123 Test St"
    )
    
    charger = await Charger.create(
        charge_point_string_id="TEST001",
        station=station,
        name="Test Charger",
        latest_status=ChargerStatusEnum.AVAILABLE
    )
    
    yield {"station": station, "charger": charger}
    
    # Cleanup
    await Tortoise.close_connections()
```

---

## Performance & Scalability

### System Performance Metrics

#### Concurrent Connection Capacity
- **WebSocket Connections**: 1000+ concurrent OCPP charger connections
- **HTTP API Throughput**: 500+ requests/second
- **Database Connections**: 20 max connections with pooling
- **Redis Operations**: Sub-millisecond connection state queries

#### Response Time Benchmarks
- **OCPP Message Processing**: <50ms average (including database operations)
- **API Endpoints**: <200ms average response time
- **Database Queries**: <10ms for indexed operations
- **Frontend Load Time**: <2 seconds initial page load
- **Map Rendering**: <1 second for 50+ station markers

### Database Performance Optimization

#### Indexing Strategy (`backend/migrations/`)
```sql
-- OCPP-optimized indexes for fast lookups
CREATE INDEX CONCURRENTLY idx_charger_charge_point_id 
    ON charger(charge_point_string_id);
CREATE INDEX CONCURRENTLY idx_charger_status_heartbeat 
    ON charger(latest_status, last_heart_beat_time);
CREATE INDEX CONCURRENTLY idx_transaction_status_charger 
    ON transaction(transaction_status, charger_id);
CREATE INDEX CONCURRENTLY idx_transaction_user_status 
    ON transaction(user_id, transaction_status);
CREATE INDEX CONCURRENTLY idx_meter_value_transaction_time 
    ON meter_value(transaction_id, created_at DESC);
CREATE INDEX CONCURRENTLY idx_ocpp_log_correlation 
    ON log(correlation_id);
CREATE INDEX CONCURRENTLY idx_ocpp_log_charger_time 
    ON log(charge_point_id, timestamp DESC);
```

#### Connection Pooling Configuration (`backend/tortoise_config.py`)
```python
TORTOISE_ORM = {
    "connections": {
        "default": {
            "engine": "tortoise.backends.asyncpg",
            "credentials": {
                "host": os.getenv("DB_HOST"),
                "port": os.getenv("DB_PORT", 5432),
                "user": os.getenv("DB_USER"),
                "password": os.getenv("DB_PASSWORD"),
                "database": os.getenv("DB_NAME"),
                "ssl": "require" if os.getenv("ENVIRONMENT") == "production" else None,
                # Connection pooling optimization
                "minsize": 5,
                "maxsize": 20,
                "max_queries": 50000,
                "max_inactive_connection_lifetime": 300,
                "timeout": 60,
                "command_timeout": 5
            }
        }
    }
}
```

### Backend Performance Optimization

#### Async Processing Architecture
```python
# Efficient bulk operations for dashboard
async def get_chargers_with_connection_status():
    # Single database query with relationships
    chargers = await Charger.all().prefetch_related('station', 'connectors')
    charger_ids = [c.charge_point_string_id for c in chargers]
    
    # Bulk Redis connection status check
    connection_statuses = await redis_manager.get_bulk_connection_status(charger_ids)
    
    # Combine results efficiently
    return [
        {
            **charger.__dict__,
            "is_connected": connection_statuses.get(charger.charge_point_string_id, False),
            "connection_status": "online" if connection_statuses.get(charger.charge_point_string_id) else "offline"
        }
        for charger in chargers
    ]
```

#### WebSocket Message Processing Pipeline
```python
async def process_ocpp_message(charge_point_id: str, message: str):
    start_time = time.time()
    
    try:
        # Parse and validate (1-2ms)
        parsed_message = json.loads(message)
        message_type = parsed_message[2]
        
        # Route to handler (1ms)
        handler = get_message_handler(message_type)
        
        # Process with database operations (10-50ms)
        response = await handler(parsed_message[3])
        
        # Performance monitoring
        processing_time = (time.time() - start_time) * 1000
        if processing_time > 100:  # Log slow messages
            logger.warning(f"Slow OCPP message: {message_type} took {processing_time:.2f}ms")
        
        return response
        
    except Exception as e:
        logger.error(f"Error processing OCPP message: {e}", exc_info=True)
        raise
```

### Frontend Performance Optimization

#### React Query Configuration (`frontend/contexts/QueryClientProvider.tsx`)
```typescript
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Optimized cache configuration
      staleTime: 1 * 60 * 1000,        // 1 minute default stale time
      cacheTime: 5 * 60 * 1000,        // 5 minutes cache time
      refetchOnWindowFocus: false,     // Reduce unnecessary refetches
      retry: 3,                        // Retry failed requests
      retryDelay: attemptIndex => Math.min(1000 * 2 ** attemptIndex, 30000),
    },
    mutations: {
      retry: 1,                        // Single retry for mutations
    },
  },
});
```

#### Query Optimization by Data Type
```typescript
// Static data - longer cache times
const useStations = () => useQuery({
  queryKey: ['stations'],
  queryFn: stationService.getAll,
  staleTime: 2 * 60 * 1000,          // 2 minutes for stations
  cacheTime: 10 * 60 * 1000,         // 10 minutes cache
});

// Dynamic data - shorter cache times
const useChargers = () => useQuery({
  queryKey: ['chargers'],
  queryFn: chargerService.getAll,
  staleTime: 10 * 1000,              // 10 seconds for chargers
  refetchInterval: 10 * 1000,        // Auto-refresh every 10 seconds
});

// Real-time data - minimal cache
const useActiveTransactions = () => useQuery({
  queryKey: ['transactions', 'active'],
  queryFn: () => transactionService.getAll({ status: 'RUNNING' }),
  staleTime: 5 * 1000,               // 5 seconds for active transactions
  refetchInterval: 5 * 1000,         // Auto-refresh every 5 seconds
});
```

#### Component Performance Optimization
```typescript
// Memoized components for expensive renders
const ChargerCard = memo(({ charger }) => {
  const statusColor = useMemo(() => getStatusColor(charger.latest_status), [charger.latest_status]);
  const lastHeartbeat = useMemo(() => formatHeartbeat(charger.last_heart_beat_time), [charger.last_heart_beat_time]);
  
  return (
    <Card className="p-4">
      <Badge className={statusColor}>{charger.latest_status}</Badge>
      <p className="text-sm text-gray-500">{lastHeartbeat}</p>
    </Card>
  );
});

// Virtualized lists for large datasets
const ChargerList = ({ chargers }) => {
  const [virtualizer] = useVirtual({
    size: chargers.length,
    parentRef: containerRef,
    estimateSize: 120,  // Estimated row height
  });
  
  return (
    <div ref={containerRef} className="h-96 overflow-auto">
      {virtualizer.virtualItems.map(virtualRow => {
        const charger = chargers[virtualRow.index];
        return (
          <div
            key={virtualRow.index}
            style={{
              position: 'absolute',
              top: 0,
              left: 0,
              width: '100%',
              height: `${virtualRow.size}px`,
              transform: `translateY(${virtualRow.start}px)`,
            }}
          >
            <ChargerCard charger={charger} />
          </div>
        );
      })}
    </div>
  );
};
```

### Scaling Architecture

#### Horizontal Scaling Support
```python
# Redis-based state enables multiple backend instances
class RedisConnectionManager:
    async def add_connected_charger(self, charger_id: str, data: dict):
        """Shared connection state across instances"""
        await self.redis_client.hset(
            "charger_connections", 
            charger_id, 
            json.dumps(data)
        )
    
    async def get_bulk_connection_status(self, charger_ids: List[str]) -> Dict[str, bool]:
        """Efficient bulk status checking"""
        if not charger_ids:
            return {}
        
        pipe = self.redis_client.pipeline()
        for charger_id in charger_ids:
            pipe.hexists("charger_connections", charger_id)
        
        results = await pipe.execute()
        return dict(zip(charger_ids, results))
```

#### Database Read Scaling
```python
# Read replica configuration (future enhancement)
TORTOISE_ORM = {
    "connections": {
        "default": {
            # Write operations
            "engine": "tortoise.backends.asyncpg",
            "credentials": {...}
        },
        "replica": {
            # Read operations for scaling
            "engine": "tortoise.backends.asyncpg", 
            "credentials": {...}  # Read replica connection
        }
    }
}
```

### Memory Management

#### Backend Memory Profile
- **Base Python Runtime**: ~100MB
- **Per OCPP Connection**: ~1MB per WebSocket connection
- **Database Connection Pool**: ~5MB per connection (20 max = 100MB)
- **Redis Connection**: ~2MB overhead
- **Expected Total**: ~500MB for 100 concurrent charger connections

#### Frontend Memory Optimization
```typescript
// Proper cleanup in useEffect hooks
useEffect(() => {
  const interval = setInterval(refetchChargers, 10000);
  return () => clearInterval(interval);  // Cleanup
}, [refetchChargers]);

// Memory-efficient infinite queries for large datasets
const useInfiniteTransactions = () => {
  return useInfiniteQuery({
    queryKey: ['transactions', 'infinite'],
    queryFn: ({ pageParam = 1 }) => 
      transactionService.getAll({ page: pageParam, limit: 20 }),
    getNextPageParam: (lastPage, pages) => 
      lastPage.data.length === 20 ? pages.length + 1 : undefined,
  });
};
```

---

## Technical Debt & Known Issues

### Critical Issues

#### 1. Boot Notification Transaction Handling — ✅ RESOLVED
**Location**: `backend/main.py:163-224`
**Resolution**: Implemented suspend/resume mechanism

**Current Behavior**:
- On `BootNotification`, ongoing transactions are marked `SUSPENDED` (not FAILED)
- A background `_suspend_timeout` task waits `SUSPEND_TIMEOUT_SECONDS` (default 300s)
- If the charger resumes the transaction (sends MeterValues or StartTransaction for same id_tag), the transaction is resumed to RUNNING
- If the timeout fires while still SUSPENDED: transaction is auto-stopped with energy calculation from last MeterValue, wallet billing, and QR payment billing/refund
- Handles double-boot race conditions via `suspended_at` timestamp comparison

**Defense-in-depth layers**:
1. **StopTransaction reason sanitization**: `route_message()` override replaces non-standard reason values (e.g., `"AppStop"`) with `"Other"` to prevent OCPP validation rejection
2. **Suspend timeout**: Safety net — QR billing/refund processed alongside wallet billing when suspended transactions time out

### Minor Technical Debt

#### 2. Database Configuration Duplication
**Location**: `backend/database.py` vs `backend/tortoise_config.py`
**Issue**: Deprecated database.py file still exists but not used

**Current State**:
- `database.py`: Legacy configuration (unused)
- `tortoise_config.py`: Active configuration

**Action Required**: Remove `backend/database.py` and update any remaining references

#### 3. Legacy API Endpoint Maintenance
**Location**: `backend/main.py:657-725`
**Issue**: Backward compatibility endpoints without proper documentation

**Current Legacy Endpoints**:
```python
@app.get("/api/charge-points")  # Legacy compatibility
@app.post("/api/charge-points/{charge_point_id}/request")  # Legacy compatibility
@app.get("/api/logs")  # Legacy compatibility
```

**Recommendation**: 
- Document these endpoints clearly as legacy
- Consider deprecation timeline
- Migrate clients to new admin APIs

#### 4. Frontend Type Safety Gaps
**Location**: Various frontend files
**Issue**: Some components lack complete TypeScript typing

**Areas for Improvement**:
- `frontend/components/QRScanner.tsx`: ZXing library types
- `frontend/app/stations/StationMap.tsx`: Leaflet event types
- API response types could be more granular

### Performance Optimization Opportunities

#### 5. Database Query Optimization
**Location**: `backend/routers/chargers.py`
**Issue**: N+1 query pattern in some charger list operations

**Current Pattern**:
```python
# Potential N+1 issue
chargers = await Charger.all()
for charger in chargers:
    connection_status = await redis_manager.is_charger_connected(charger.charge_point_string_id)
```

**Optimization**:
```python
# Bulk operation
chargers = await Charger.all()
charger_ids = [c.charge_point_string_id for c in chargers]
connection_statuses = await redis_manager.get_bulk_connection_status(charger_ids)
```

#### 6. Frontend Bundle Size
**Current Bundle**: ~2MB JavaScript bundle
**Opportunity**: Code splitting for admin-only features
**Potential Savings**: 30-40% reduction for user-only builds

### Security Considerations

#### 7. OCPP Message Validation
**Location**: `backend/main.py` message handlers
**Issue**: Limited OCPP message schema validation

**Current State**: Basic parameter validation
**Improvement**: Comprehensive OCPP 1.6 schema validation
**Impact**: Better protocol compliance and security

#### 8. Rate Limiting
**Status**: Not implemented
**Risk**: API abuse potential
**Solution**: Implement rate limiting middleware for public endpoints

### Monitoring & Observability

#### 9. Performance Metrics Collection
**Current**: Basic logging with correlation IDs
**Missing**: 
- Response time metrics by endpoint
- OCPP message processing time tracking
- Database query performance monitoring
- Memory usage tracking

**Recommended Tools**: 
- OpenTelemetry integration
- Prometheus metrics collection
- Grafana dashboards

#### 10. Error Alerting
**Current**: Console logging
**Missing**: 
- Critical error alerting
- Failed transaction notifications
- Connection failure alerts

### Future Architecture Considerations

#### 11. Microservices Migration Path
**Current**: Monolithic FastAPI application
**Future Consideration**: Domain-based service separation
- OCPP Communication Service
- Transaction Management Service  
- User Management Service
- Billing Service

**Prerequisites**: Message queue implementation (Redis Streams/RabbitMQ)

#### 12. Event Sourcing for Transactions
**Current**: State-based transaction storage
**Future Enhancement**: Event sourcing for complete transaction audit trail
**Benefits**: Better debugging, transaction replay capability, regulatory compliance

---

## Deployment & Operations

### Current Production Architecture

```
┌─────────────────────────────────────────────────────────────┐
│              AWS EC2 — Docker Compose (app.voltlync.com)     │
├─────────────────┬───────────────────────┬───────────────────┤
│                 │                       │                   │
│   Nginx         │      Backend          │   Infrastructure  │
│   (Reverse      │      (Docker)         │   (Docker)        │
│    Proxy)       │                       │                   │
│  ┌─────────────┐│  ┌─────────────────┐  │ ┌─────────────┐   │
│  │ SSL/TLS     ││  │   FastAPI App   │  │ │ PostgreSQL  │   │
│  │ termination ││  │                 │  │ │  Database   │   │
│  │ WebSocket   ││  │ • OCPP Server   │  │ │             │   │
│  │ proxy       ││  │ • REST APIs     │  │ │ • Persistent│   │
│  │ Rate limit  ││  │ • WebSocket     │  │ │   volume    │   │
│  │             ││  │ • Background    │  │ │ • Auto-     │   │
│  │             ││  │   Services      │  │ │   migrate   │   │
│  └─────────────┘│  └─────────────────┘  │ └─────────────┘   │
│                 │                       │                   │
│  ┌─────────────┐│  ┌─────────────────┐  │ ┌─────────────┐   │
│  │  Next.js    ││  │    Clerk        │  │ │    Redis    │   │
│  │  Frontend   ││  │    Auth         │  │ │             │   │
│  │  (Docker)   ││  │                 │  │ │ • 256mb max │   │
│  │             ││  │ • JWT Tokens    │  │ │ • allkeys-  │   │
│  │ • Standalone││  │ • Webhooks      │  │ │   lru       │   │
│  │   output    ││  │                 │  │ │ • QR session│   │
│  └─────────────┘│  └─────────────────┘  │ └─────────────┘   │
└─────────────────┴───────────────────────┴───────────────────┘
```

### Docker Compose Deployment

**Services**: 5 containers — `backend`, `frontend`, `nginx`, `postgres`, `redis`
**Configs**: `docker-compose.yml` (dev), `docker-compose.prod.yml` (production)
**Makefile**: 60+ targets for deployment automation (`make prod-deploy`, `make prod-rebuild`, etc.)

#### Environment Variables (Production)
```bash
# Database Configuration
DB_HOST=postgres
DB_PORT=5432
DB_USER=...
DB_PASSWORD=...
DB_NAME=ocpp_db

# Redis Configuration
REDIS_URL=redis://redis:6379

# Clerk Authentication
CLERK_SECRET_KEY=sk_live_...
CLERK_WEBHOOK_SECRET=whsec_...

# Razorpay Payment Gateway
RAZORPAY_KEY_ID=rzp_live_...
RAZORPAY_KEY_SECRET=...
RAZORPAY_PLATFORM_FEE_PERCENT=2.0  # Authoritative synthetic rate for customer-facing math (ADR 0001)

# Transaction Suspend/Resume
DISCONNECT_SUSPEND_TIMEOUT_SECONDS=180  # Timeout after charger disconnect (before marking STOPPED)
SUSPEND_TIMEOUT_SECONDS=300              # Timeout after BootNotification (resume window)

# Monitoring
SENTRY_ENABLED=true
SENTRY_DSN=...
NEW_RELIC_MONITOR_MODE=true
NEW_RELIC_LICENSE_KEY=...

# Data Retention
RETENTION_DAYS=90
CLEANUP_INTERVAL_HOURS=24
```

#### Deployment Process
1. **SSH to EC2**: Connect to production server
2. **Pull Latest**: `git pull origin deploy`
3. **Rebuild**: `make prod-rebuild` (multi-stage Docker builds)
4. **Auto-Migrate**: `docker-entrypoint.sh` runs Aerich migrations on backend startup
5. **Health Check**: `GET /health` endpoint validates readiness
6. **Nginx**: SSL termination, WebSocket proxying for `/ocpp/`, rate limiting

### Frontend Configuration
- **Output**: `standalone` mode for Docker production builds
- **Next.js 15.3.8** with App Router, React 19
- **Environment**: `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_APP_URL`, `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`

### Database Management

#### PostgreSQL Configuration
```sql
-- Production database settings
-- Connection pool settings handled by Tortoise ORM
ALTER SYSTEM SET max_connections = '100';
ALTER SYSTEM SET shared_buffers = '256MB';
ALTER SYSTEM SET effective_cache_size = '1GB';
ALTER SYSTEM SET work_mem = '4MB';

-- SSL requirements for production
ALTER SYSTEM SET ssl = 'on';
ALTER SYSTEM SET ssl_cert_file = 'server.crt';
ALTER SYSTEM SET ssl_key_file = 'server.key';
```

#### Migration Management
```bash
# Production migration commands
cd backend

# Generate new migration
aerich migrate --name "description"

# Review migration before applying
cat migrations/models/*.py

# Apply migration to production (via deployment)
aerich upgrade
```

#### Backup Strategy
- **Automated Daily Backups**: Managed by hosting provider
- **Point-in-time Recovery**: Available through managed database service
- **Backup Verification**: Regular restore testing
- **Data Retention**: 30-day backup retention policy

### Redis Configuration

#### Connection Configuration
```python
# Production Redis settings
REDIS_CONFIG = {
    "host": os.getenv("REDIS_HOST"),
    "port": int(os.getenv("REDIS_PORT", 6379)),
    "password": os.getenv("REDIS_PASSWORD"),
    "ssl": True if os.getenv("ENVIRONMENT") == "production" else False,
    "socket_timeout": 5,
    "socket_connect_timeout": 5,
    "health_check_interval": 30,
}
```

#### Data Persistence
- **Connection State**: Ephemeral data, acceptable loss
- **Session Cache**: TTL-based expiration
- **Pub/Sub**: Real-time notifications (future feature)

### Monitoring & Logging

#### Application Logging (`backend/main.py:34-38`)
```python
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),  # Console output for cloud logging
        # File logging disabled in production (use cloud logging)
    ]
)
```

#### Structured Logging
- **Correlation IDs**: All OCPP messages include correlation tracking
- **Request Context**: User context in all API operations
- **Performance Metrics**: Response time logging for slow operations
- **Error Context**: Stack traces with request context

#### Health Monitoring
```python
# Health check endpoint
@app.get("/")
def health_check():
    return {
        "status": "healthy",
        "version": "2.0",
        "timestamp": datetime.utcnow().isoformat(),
        "services": {
            "database": "connected",  # Could add actual checks
            "redis": "connected",
            "ocpp": "active"
        }
    }
```

### Security Configuration

#### SSL/TLS Configuration
- **Frontend**: Automatic HTTPS via Vercel
- **Backend**: SSL termination at Render load balancer
- **Database**: SSL-required connections
- **Redis**: SSL connections in production

#### CORS Policy (Production)
```python
# backend/main.py:47-54
CORS_ORIGINS = [
    "https://ocpp-frontend-mu.vercel.app",  # Production frontend
    "http://localhost:3000",                # Development
]
```

### Scaling & Performance

#### Auto-Scaling Configuration
- **Backend**: Render auto-scaling based on CPU/memory usage
- **Frontend**: Vercel global edge deployment
- **Database**: Managed scaling with connection pooling
- **Redis**: Managed scaling with clustering (if needed)

#### Performance Monitoring
- **Response Times**: Application-level logging
- **Database Performance**: Query performance monitoring
- **Connection Health**: OCPP connection state tracking
- **Error Rates**: Exception tracking and alerting

### Disaster Recovery

#### Backup Procedures
1. **Database Backups**: Daily automated backups with 30-day retention
2. **Configuration Backup**: Environment variables documented and version controlled
3. **Code Repository**: Git-based source control with multiple branches
4. **Deployment Rollback**: Quick rollback capability via hosting platforms

#### Recovery Procedures
1. **Service Outage**: Automatic health check and restart
2. **Database Recovery**: Point-in-time recovery from backups
3. **Configuration Recovery**: Environment variable restoration
4. **Full System Recovery**: Complete redeployment from source control

#### Business Continuity
- **RTO (Recovery Time Objective)**: 15 minutes for service restoration
- **RPO (Recovery Point Objective)**: Maximum 1 hour data loss
- **Monitoring**: Real-time alerting for critical service failures
- **Communication**: Status page for user communication during outages

---

## Recent Changes & Updates

### Latest Release - March 2026 (Branch: 57-qr-based-appless-transaction)

#### New Features Implemented

**1. QR-Based Appless Charging** (Major Feature)
- **Feature**: Customers can scan a Razorpay UPI QR code at a charger and pay any amount to start charging — no app or account needed
- **Implementation**:
  - New `ChargerQRCode` model linking Razorpay QR codes to chargers
  - New `QRPayment` model tracking payment lifecycle (PAID → CHARGING → COMPLETED → REFUNDED)
  - `QRPaymentService` with full lifecycle: webhook → user resolution → RemoteStart → budget enforcement → billing → refund
  - Redis-cached session data (`qr_session:{txn_id}`) for budget checking during MeterValues
  - Budget enforcement: auto-stops charging when cost >= budget limit
  - Automated partial refund of unused balance via Razorpay
  - UPI_GUEST user creation for new customers (phone/VPA-based lookup)
- **Safety & Error Handling**:
  - Idempotent webhook processing (razorpay_payment_id uniqueness)
  - Stale payment detection (>5 min old → auto-refund)
  - Double-payment guard (refund if charger already active)
  - Charger disconnect detection with auto-refund
  - Plug-in timeout (5 min polling, then refund)
  - RemoteStart retry (2 attempts, 5s delay)
  - Refund below ₹1 absorbed as operator credit
- **Admin UI**:
  - `/admin/qr-codes` - QR code list with create/close actions, revenue stats
  - `/admin/qr-codes/[id]` - Detail page with QR image, payment history, refund tracking
- **API Endpoints**:
  - `POST /api/admin/qr-codes` - Create QR code for charger
  - `GET /api/admin/qr-codes` - List with pagination, search, status filter
  - `GET /api/admin/qr-codes/{id}` - Detail with payment stats
  - `POST /api/admin/qr-codes/{id}/close` - Deactivate QR code
  - `GET /api/admin/qr-codes/{id}/payments` - Payment history
  - `POST /webhooks/razorpay` (qr_code.credited event) - Webhook handler
- **Database Migrations**: 3 new migrations (10, 11, 12)
- **Configuration**: `RAZORPAY_PLATFORM_FEE_PERCENT`, `QR_PAYMENT_PENDING_TIMEOUT`
- **Files Added**:
  - `backend/services/qr_payment_service.py` - Core service (~600 lines)
  - `backend/routers/qr_codes.py` - Admin API router
  - `backend/scripts/test_qr_webhook.py` - Local webhook simulation
  - `frontend/app/admin/qr-codes/page.tsx` - QR list page
  - `frontend/app/admin/qr-codes/[id]/page.tsx` - QR detail page
  - `frontend/lib/queries/qr-codes.ts` - TanStack Query hooks
- **Files Modified**:
  - `backend/main.py` - StartTransaction (link QR), MeterValues (budget check), StopTransaction (billing)
  - `backend/models.py` - ChargerQRCode, QRPayment, QRPaymentStatusEnum, AuthProviderEnum
  - `backend/routers/webhooks.py` - Added qr_code.credited routing
  - `backend/redis_manager.py` - Added QR session cache methods
  - `frontend/lib/api-services.ts` - qrCodeService
  - `frontend/types/api.ts` - ChargerQRCode, QRPayment types

**2. Docker Compose Production Deployment**
- Complete containerized deployment with Docker Compose
- Multi-stage Docker builds for backend (Python) and frontend (Next.js)
- Nginx reverse proxy with SSL, WebSocket proxying, rate limiting
- Separate configs: docker-compose.yml (dev), staging, prod
- Makefile with 30+ management targets
- Environment templates: .env.docker.example, .env.staging.example, .env.prod.example

**3. Monitoring & Observability**
- Sentry integration with ASGI middleware for error tracking
- New Relic APM with custom `@trace_transaction` decorator for OCPP messages
- Structured logging with timestamps and correlation IDs
- Connection manager refactored to `core/connection_manager.py`
- Monitoring service: `services/monitoring_service.py`

**4. Transaction Suspend/Resume + Disconnect Handling**
- **Feature**: Charging transactions survive charger reboots and power failures instead of being lost
- **Implementation**:
  - **Disconnect handler** (`services/disconnect_handler.py`): When charger disconnects (heartbeat timeout), active transactions are immediately SUSPENDED with a 180s timeout. If charger doesn't reconnect, transactions are STOPPED with billing + QR refund.
  - **BootNotification**: Already-SUSPENDED transactions get their timeout reset (CAS guard invalidates old disconnect timeout), and a new 300s resume window starts. Still-active transactions (edge case) are suspended as before.
  - **Startup sweep**: `sweep_stale_suspended_transactions()` catches orphaned SUSPENDED transactions from server restarts.
  - DataTransfer `GetLastMeterValue` handler allows charger to request last meter reading for seamless resume
  - Transaction model extended with `suspended_at`, `resumed_at`, `resume_count` fields
  - Auto-stop processes full wallet billing + QR payment billing/refund
  - ConnectionManager `register_on_disconnect()` callback hook fires on `force_disconnect()`
- **Migration**: `8_20260305050220_add_transaction_resume_fields.py`
- **Configuration**: `DISCONNECT_SUSPEND_TIMEOUT_SECONDS` (default 180), `SUSPEND_TIMEOUT_SECONDS` (default 300)
- **Files Added**:
  - `backend/services/disconnect_handler.py` - Transaction suspension, timeout, auto-stop with billing
  - `backend/simulators/ocpp_simulator_disconnect.py` - Synchronous simulator with 3 test modes (no-reconnect, reconnect, no-transaction)
- **Files Modified**:
  - `backend/core/connection_manager.py` - `register_on_disconnect()` callback hook, `force_disconnect()` fires callbacks
  - `backend/main.py` - Startup wiring for disconnect callback + `sweep_stale_suspended_transactions()`

**5. StopTransaction Reason Sanitization**
- **Feature**: Prevents OCPP validation rejection when charger firmware sends non-standard stop reason values
- **Implementation**:
  - `ChargePoint.route_message()` override intercepts StopTransaction messages
  - Non-standard reason values (e.g., `"AppStop"`) are sanitized to `"Other"` before OCPP schema validation
  - Original value logged as warning for debugging
- **Valid OCPP 1.6 Reasons**: EmergencyStop, EVDisconnected, HardReset, Local, Other, PowerLoss, Reboot, Remote, SoftReset, UnlockCommand, DeAuthorized

**6. Enhanced Billing Retry Service**
- **Feature**: Background service now handles QR refund retries, orphaned payment cleanup, and stale suspended transactions
- **Implementation**:
  - Runs every 30 minutes as asyncio background loop
  - `_process_failed_billing_transactions()` - Retries BILLING_FAILED transactions
  - `_process_failed_qr_refunds()` - Retries REFUND_FAILED QR payments via Razorpay
  - `_cleanup_orphaned_qr_payments()` - Detects and refunds QR payments stuck in PAID status with no linked transaction
  - `_cleanup_stale_suspended_transactions()` - Auto-stops SUSPENDED transactions older than 5 hours
  - Per-item error handling (one failure doesn't block others)

**7. Remote Start Double Prevention**
- **Feature**: Prevents duplicate charging sessions when webhook retries overlap with already-started transactions
- **Implementation**: After RemoteStart timeout, checks if a transaction has already started (charger status == CHARGING) before retrying

**8. Logging Improvements**
- Root logger configured with timestamps (`force=True`)
- App-specific logger with `propagate=False` to avoid duplicate output
- Timezone-aware log timestamps
- Better visibility into OCPP message flow

---

### Previous Release - January 2026 (Branch: 47-new-relic)

#### New Features Implemented

**1. Charger Error Tracking System**
- **Feature**: Complete OCPP StatusNotification error capture with vendor error code support
- **Implementation**:
  - New `ChargerError` model stores all error events from StatusNotification
  - Captures standard OCPP error codes (GroundFailure, HighTemperature, etc.)
  - Captures vendor-specific error codes (`vendorErrorCode` field)
  - Auto-resolves errors when `error_code="NoError"` is received
  - Resolution timestamp tracking
- **API Endpoints**:
  - `GET /api/admin/chargers/{id}/errors` - Error history with pagination
  - `GET /api/admin/chargers/{id}/errors/latest` - Latest unresolved error
- **Frontend**:
  - Error history table on charger detail page (last 7 days)
  - Color-coded badges: red for OCPP error codes, orange for vendor codes
  - Resolution status indicators (green=resolved, yellow=unresolved)
  - Charger list shows latest error with clear distinction
- **Files Added**:
  - `backend/migrations/models/6_20260113163547_add_admin_and_charger_error.py`
  - `backend/simulators/ocpp_simulator_vendor_errors.py`
- **Files Modified**:
  - `backend/models.py` - ChargerError model
  - `backend/main.py` - StatusNotification handler with error capture
  - `backend/routers/chargers.py` - Error history endpoints
  - `frontend/lib/api-services.ts` - chargerErrorService
  - `frontend/lib/queries/chargers.ts` - useChargerErrors hook
  - `frontend/app/admin/chargers/[id]/page.tsx` - Error history display
  - `frontend/app/admin/chargers/page.tsx` - Error column improvements

**2. OCPP Compliance Improvements**
- **Heartbeat Interval**: Changed from 300s to 30s for more responsive connection monitoring
- **ChangeAvailability**: Now OCPP 1.6 compliant - can be sent at any time, not just for Available/Unavailable statuses
- **Files Modified**:
  - `backend/main.py` - BootNotification response interval
  - `backend/routers/chargers.py` - ChangeAvailability endpoint
  - `frontend/app/admin/chargers/page.tsx` - Availability toggle logic

---

### Previous Release - December 2025 (Branch: 39-feature---user-transaction-pages-zero-charged-transactions)

#### New Features Implemented

**1. Zero Charged Transaction Handling** (Commit: e3f6b38)
- **Feature**: Graceful handling of transactions with 0 kWh energy consumption
- **Implementation**:
  - Modified `WalletService.process_transaction_billing()` to detect zero energy
  - Returns success without wallet deduction
  - Transaction status set to COMPLETED (not BILLING_FAILED)
- **Use Case**: Handles test sessions, aborted charging, or diagnostic transactions
- **Files Modified**: `backend/services/wallet_service.py`

**2. User Transaction Pages** (Commit: e3f6b38)
- **Admin Views**:
  - `/admin/users/[id]/transactions` - Paginated charging transaction history
  - `/admin/users/[id]/wallet` - Wallet transaction history with running balance
- **Features**:
  - Transaction status badges with color coding
  - Energy consumption and duration display
  - Running balance calculation for wallet transactions
  - Pagination (10 charging transactions, 15 wallet transactions per page)
  - Filter and search capabilities
- **Files Added**:
  - `frontend/app/admin/users/[id]/transactions/page.tsx`
  - `frontend/app/admin/users/[id]/wallet/page.tsx`

**3. My Sessions Page** (Commit: e3f6b38)
- **User View**: `/my-sessions` - Combined charging and wallet activity
- **Features**:
  - Current wallet balance with 30-second auto-refresh
  - Unified timeline of all user transactions
  - Mobile-responsive design
  - Quick access to transaction details
- **Files Added**: `frontend/app/my-sessions/page.tsx`

**4. Running Balance Calculation**
- **Feature**: Real-time balance calculation for wallet transaction history
- **Implementation**: Frontend calculates cumulative balance after each transaction
- **Display**: Shows balance progression over time for better transparency

#### Backend Improvements

**1. WebSocket Connection Management** (Commits: b385b61, 9fe8f2f)
- Enhanced debugging for WebSocket disconnections
- Improved ghost session cleanup
- Natural disconnect handling improvements
- Connection state logging enhancements

**2. Timing Adjustments** (Commit: c42f1fc)
- Heartbeat timeout: 90 seconds (configurable)
- Periodic cleanup: 5 minutes
- Stale connection threshold: 90 seconds
- Improved connection reliability

**3. Energy Display Improvements** (Commit: 38816d3)
- Fixed decimal precision in energy display (shows 0.01 kWh accuracy)
- Chart downloadable functionality (CSV export)
- Improved chart scales for readability
- Better meter value visualization

#### API Enhancements

**New Endpoints Added**:
```
GET /users/{id}/transactions          # User charging transaction list
GET /users/{id}/transactions-summary  # Transaction summary statistics
GET /users/{id}/wallet-transactions   # Wallet transaction history
GET /users/my-sessions                # Current user's all transactions
```

**Improved Endpoints**:
- Enhanced transaction queries with better pagination
- Wallet balance queries with running balance calculation
- Transaction summary with energy and cost aggregations

#### Frontend Improvements

**1. TanStack Query Integration**
- New query hooks for user transactions: `useUserTransactions()`
- New query hooks for wallet transactions: `useUserWalletTransactions()`
- Optimized caching strategies for transaction data
- Auto-refresh intervals for real-time updates

**2. Component Updates**
- Transaction status badge component with color coding
- Wallet transaction display with type indicators
- Running balance display in transaction history
- Mobile-responsive transaction tables

### Recent Bug Fixes

1. **Zero Energy Billing** - Fixed billing failures for 0 kWh transactions
2. **Decimal Precision** - Fixed energy display to show proper decimal places
3. **Chart Scaling** - Improved chart readability with better axis scaling
4. **Connection Cleanup** - Fixed ghost session issues in WebSocket connections

### Performance Improvements

1. **Database Queries**: Optimized user transaction queries with proper indexing
2. **Frontend Bundle**: Improved code splitting for user transaction pages
3. **API Response Times**: Reduced response times for wallet transaction queries
4. **Real-time Updates**: Implemented efficient polling strategies (30s for balance, 10s for active sessions)

---

## Future Roadmap

### Short-term Enhancements (Next 3 months)

#### Technical Debt Resolution
1. **Boot Notification Fix** (Priority: Critical)
   - Implement transaction reconciliation logic
   - Add PENDING_RECONCILIATION status
   - Status verification via StatusNotification messages
   - Automatic cleanup for orphaned transactions

2. **Enhanced OCPP Command Support**
   - ✅ `Reset` command - Implemented (Hard/Soft with safety validation)
   - `GetConfiguration/ChangeConfiguration` for dynamic settings
   - `UnlockConnector` for emergency release
   - `ClearCache` for authorization management

3. **Performance Optimization**
   - Database query optimization for N+1 patterns
   - Redis connection pooling improvements
   - Frontend bundle size reduction through code splitting
   - OCPP message processing pipeline optimization

#### Security Enhancements
```python
# Planned: OCPP message schema validation
class OCPPMessageValidator:
    def validate_boot_notification(self, message: dict) -> bool:
        required_fields = ["chargePointVendor", "chargePointModel"]
        return all(field in message for field in required_fields)
    
    def validate_meter_values(self, message: dict) -> bool:
        # Comprehensive OCPP 1.6 schema validation
        pass
```

- **Rate Limiting**: API endpoint protection
- **OCPP Message Validation**: Complete schema validation
- **Audit Logging**: Enhanced security event logging
- **API Key Management**: Alternative authentication method

### Medium-term Development (3-6 months)

#### Advanced Analytics & Reporting
```python
# Planned: Advanced analytics service
class EnergyAnalyticsService:
    async def calculate_usage_patterns(self, user_id: int) -> dict:
        """Analyze user charging patterns"""
        pass
    
    async def generate_carbon_footprint_report(self, station_id: int) -> dict:
        """Calculate environmental impact"""
        pass
    
    async def predict_maintenance_needs(self, charger_id: int) -> dict:
        """Predictive maintenance analysis"""
        pass
```

**Features**:
- Energy consumption analytics with trend analysis
- Carbon footprint tracking and reporting
- Predictive maintenance based on usage patterns
- Revenue analytics with forecasting
- User behavior analysis and insights

#### Enhanced User Experience
```typescript
// Planned: Advanced PWA features
class NotificationService {
  async requestPermission(): Promise<boolean> {
    // Push notification permission
  }
  
  async subscribeToChargerUpdates(chargerId: string): Promise<void> {
    // Real-time charger status notifications
  }
  
  async notifyChargingComplete(transactionId: number): Promise<void> {
    // Charging session completion alerts
  }
}
```

**Features**:
- Push notifications for charging status updates
- Offline functionality with service worker caching
- Advanced QR code features (bulk operations, favorites)
- Intelligent station recommendations based on usage patterns
- Integration with calendar apps for charging scheduling

#### Multi-tenant Architecture
```python
# Planned: Multi-tenancy support
class TenantService:
    async def create_tenant(self, tenant_data: dict) -> Tenant:
        """Create isolated tenant environment"""
        pass
    
    async def get_tenant_chargers(self, tenant_id: int) -> List[Charger]:
        """Tenant-specific charger filtering"""
        pass
    
    async def configure_tenant_billing(self, tenant_id: int, config: dict) -> bool:
        """Custom billing configuration per tenant"""
        pass
```

### Long-term Vision (6-12 months)

#### OCPP 2.0.1 Migration
```python
# Planned: OCPP 2.0.1 support with backward compatibility
class OCPP201Handler:
    async def handle_security_event_notification(self, message: dict) -> dict:
        """Enhanced security features in OCPP 2.0.1"""
        pass
    
    async def handle_device_model_notification(self, message: dict) -> dict:
        """Advanced device management"""
        pass
    
    async def handle_iso15118_certificate_installation(self, message: dict) -> dict:
        """Plug & Charge support"""
        pass
```

**Features**:
- Certificate-based authentication
- Enhanced security profiles
- ISO 15118 Plug & Charge integration
- Advanced device management
- Smart charging capabilities

#### Smart Grid Integration
```python
# Planned: Smart grid features
class SmartGridManager:
    async def optimize_charging_schedule(self, grid_data: dict) -> dict:
        """Load balancing across charging network"""
        pass
    
    async def implement_demand_response(self, event: dict) -> dict:
        """Grid demand response participation"""
        pass
    
    async def calculate_renewable_energy_usage(self, period: dict) -> dict:
        """Renewable energy tracking and optimization"""
        pass
```

**Capabilities**:
- Dynamic load balancing across charging network
- Peak demand management and load shifting
- Renewable energy integration and tracking
- Grid services participation (V2G, demand response)
- Real-time pricing based on grid conditions

#### Machine Learning Integration
```python
# Planned: ML-powered insights
class ChargingIntelligenceService:
    async def predict_charging_demand(self, location: dict, timeframe: dict) -> dict:
        """Demand forecasting model"""
        pass
    
    async def detect_charging_anomalies(self, charger_id: int) -> dict:
        """Anomaly detection for maintenance"""
        pass
    
    async def recommend_optimal_locations(self, criteria: dict) -> List[dict]:
        """Site selection optimization"""
        pass
```

**AI Features**:
- Charging demand forecasting
- Anomaly detection for predictive maintenance
- Optimal charging station placement analysis
- User behavior pattern recognition
- Dynamic pricing optimization

#### Advanced Payment & Billing
```python
# Planned: Enhanced payment systems
class AdvancedPaymentService:
    async def process_cryptocurrency_payment(self, transaction: dict) -> dict:
        """Bitcoin/Ethereum payment processing"""
        pass
    
    async def handle_roaming_agreement(self, partner_network: str, user: dict) -> dict:
        """Inter-network charging support"""
        pass
    
    async def calculate_dynamic_pricing(self, charger: dict, demand: dict) -> decimal:
        """Time-of-use and demand-based pricing"""
        pass
```

### Technology Evolution

#### Microservices Architecture
```yaml
# Planned: Kubernetes deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ocpp-communication-service
spec:
  replicas: 3
  selector:
    matchLabels:
      app: ocpp-communication
  template:
    spec:
      containers:
      - name: ocpp-service
        image: ocpp-communication:latest
        ports:
        - containerPort: 8000
        env:
        - name: SERVICE_TYPE
          value: "ocpp-communication"
```

**Service Decomposition**:
- OCPP Communication Service: WebSocket handling and protocol processing
- Transaction Management Service: Charging session lifecycle
- User Management Service: Authentication and profile management
- Billing Service: Payment processing and financial operations
- Analytics Service: Data processing and insights generation
- Notification Service: Real-time alerts and communications

#### Event-Driven Architecture
```python
# Planned: Event streaming with Kafka/Redis Streams
class EventBus:
    async def publish_charger_status_changed(self, event: dict) -> None:
        """Publish charger status change events"""
        await self.event_stream.xadd("charger-events", event)
    
    async def subscribe_to_transaction_events(self, handler) -> None:
        """Subscribe to transaction lifecycle events"""
        async for message in self.event_stream.xread({"transaction-events": "$"}):
            await handler(message)
```

#### Cloud-Native Features
- **Container Orchestration**: Kubernetes deployment with auto-scaling
- **Service Mesh**: Istio for service communication and security
- **Observability**: OpenTelemetry, Prometheus, and Grafana integration
- **CI/CD Pipeline**: GitOps with automated testing and deployment
- **Infrastructure as Code**: Terraform for infrastructure management

### Regulatory & Standards Compliance

#### Emerging Standards
- **OCPP 2.1**: Next-generation protocol support when available
- **ISO 15118-20**: Enhanced vehicle-to-grid communication
- **OSCP 2.0**: Open Smart Charging Protocol integration
- **OCHP**: Open Clearing House Protocol for roaming

#### Regional Compliance
- **GDPR**: Enhanced data protection and privacy features
- **CCPA**: California Consumer Privacy Act compliance
- **Accessibility**: WCAG 2.1 AA compliance for all interfaces
- **Security**: SOC 2 Type II certification readiness

This comprehensive roadmap ensures the OCPP CSMS remains at the forefront of EV charging technology while maintaining reliability, security, and user experience excellence. The phased approach allows for incremental improvements while building toward a next-generation charging platform.

---

## Conclusion

This OCPP 1.6 Charging Station Management System represents a comprehensive, production-ready solution for managing electric vehicle charging infrastructure in the modern era. The system successfully combines:

### Technical Excellence
- **Full OCPP 1.6 Compliance**: Complete implementation of all core messages and remote commands
- **Modern Architecture**: Async Python backend with React frontend, leveraging cutting-edge technologies
- **Real-time Capabilities**: WebSocket-based OCPP communication with Redis-backed connection management
- **Comprehensive Testing**: Multi-tier testing strategy ensuring reliability and protocol compliance
- **Production Deployment**: Successfully deployed on modern cloud platforms with proper monitoring

### Business Value
- **Role-Based Access Control**: Sophisticated RBAC system supporting both administrative and end-user workflows
- **Financial Integration**: Complete billing system with wallet management and retry mechanisms
- **User Experience Excellence**: Interactive maps, QR code scanning, and mobile-responsive design
- **Operational Efficiency**: Administrative dashboards with real-time monitoring and remote control capabilities
- **Scalable Foundation**: Architecture designed for horizontal growth and multi-tenant deployment

### Innovation & Future-Readiness
- **Authentication Evolution**: Modern Clerk-based authentication replacing traditional approaches
- **Performance Optimization**: Sophisticated caching strategies and query optimization
- **Technical Debt Management**: Clear identification and remediation path for known issues
- **Extensibility**: Plugin architecture ready for OCPP 2.0.1 migration and smart grid integration

### Production Maturity
The system demonstrates production-grade characteristics through:
- Comprehensive error handling and graceful degradation
- Complete audit trail for regulatory compliance
- Robust connection management with automatic cleanup
- Optimistic UI updates with rollback capabilities
- Structured logging with correlation tracking

**Current Status**: Actively deployed on AWS EC2 with Docker Compose, managing real-world charging infrastructure with QR-based appless charging
**Document Version**: 3.0
**Last Updated**: March 2025
**Maintainer**: OCPP Development Team

This architecture documentation serves as both a technical reference and a strategic foundation for the continued evolution of EV charging infrastructure management, positioning the system for long-term success in the rapidly advancing electric vehicle ecosystem.