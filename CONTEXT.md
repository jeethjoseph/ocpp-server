# OCPP Server

CSMS managing EV charging stations under the VoltLync brand, accepting both wallet-funded and QR/UPI-prepaid sessions across operator-franchisee chargers.

## Language

### Sessions and funding

**Charging Session** / **Session**:
A single OCPP transaction from StartTransaction to StopTransaction, identified by the charger-assigned `transaction_id`.
_Avoid_: charge, charging event.

**Wallet Session**:
A session funded from the user's `Wallet`; billed at StopTransaction by debiting the wallet ledger.
_Avoid_: app session.

**QR Session** / **Appless Session**:
A session funded by a one-time UPI payment scanned from the charger's QR sticker; the user is a `UPI_GUEST` or a pre-existing user matched by phone/VPA.
_Avoid_: guest session, anonymous session.

**Zero-energy Session**:
A session that ended with `energy_consumed_kwh ≤ 0`. For **QR Sessions** this triggers a full refund and no GST invoice; for **Wallet Sessions** no debit occurs.
_Avoid_: failed session (charger faults are a separate category).

**Internal-role Session**:
A **Charging Session** initiated by an ADMIN or FRANCHISEE user, regardless of funding source. Purely operational — VoltLync staff testing a charger or a franchisee charging their own car at their own station. No **GST Invoice** is issued, no **Wallet** is debited, no **Budget cap** is enforced. The OCPP audit trail and meter values are still recorded so ops can see "this admin burned X kWh testing." If a FRANCHISEE wants to be billed for charging, they register a separate USER account.

Working assumption (2026-05-19): internal users do not in practice scan QR codes or initiate UPI payments — those flows are customer-only. If that ever changes, the scope of this term needs to narrow to "wallet-funded + admin-triggered only" so external-money QR sessions still issue a GST invoice.
_Avoid_: test session, ops session (both are used informally in code comments but neither is the canonical term).

**Internal-role User**:
A `User` row whose `role` is `ADMIN` or `FRANCHISEE`. The canonical set is `INTERNAL_ROLES = {ADMIN, FRANCHISEE}` in `services/invoice_service.py`. These users do not require a `Wallet` and any **Charging Session** they initiate is an **Internal-role Session**.
_Avoid_: staff user, operator user.

**Live energy consumed**:
The kWh delivered so far in an in-progress **Charging Session**, derived per-request as `latest_meter_value.reading_kwh − transaction.start_meter_kwh`. Distinct from the stored column `Transaction.energy_consumed_kwh`, which is the **finalised** figure written only at StopTransaction (and possibly capped to billable kWh by the QR budget). Admin/UI surfaces that need a live readout MUST use the derived value — reading the column mid-session returns NULL and is the source of the "0.00 kWh" tile bug fixed in [[issue-01-live-energy-consumed]].
_Avoid_: "energy consumed" without qualifier when context is ambiguous between live and finalised.

### Hardware

**Charger** / **EVSE**:
A single charging unit identified by its OCPP `charge_point_string_id`. State is tracked via `ChargerStatusEnum` (`AVAILABLE`, `CHARGING`, `FAULTED`, …) and the OCPP heartbeat. The unit of "availability" customers see and the unit our budget cap / RemoteStop dispatch operate on.

**Connector**:
A physical plug on a `Charger` (e.g. Type2, Socket, CCS), modelled as a `Connector` row with `connector_type` and `max_power_kw`. **Working invariant (2026-05-21):** every `Charger` in our fleet has exactly one `Connector`. The data model permits N:1 but no current deployment uses it, and no per-connector OCPP state is tracked.

**Plug type**:
A `Connector.connector_type` value (Type2, Socket, CCS, …). Customer-facing groupings on the station map and modal are by **plug type**, but the underlying counts are charger-level — see [[ui-station-modal-chargers]] for the rendering rule.
_Avoid_: "connector" as a customer-facing label when you mean "charger of plug type X". Renamed in the public station modal 2026-05-21 to avoid the conflation.

### Firmware

**Firmware deployment** / **Deploy**:
The admin action of scheduling a firmware version onto one or more **Chargers**. A deployment creates or resets a `FirmwareUpdate` row to PENDING per charger; the background scheduler later dispatches the OCPP `UpdateFirmware`. A **bulk deployment** is the same action applied to a multi-selected set of chargers from the **Firmware Library**, scoped by the picker's current filter (e.g. one station, or "all not already on this version").
_Avoid_: "push", "flash" as the canonical verb (fine informally; "deploy" is the term).

**In-flight firmware update**:
A `FirmwareUpdate` row that is PENDING with `attempt_count > 0` — the server has already dispatched at least one `UpdateFirmware` and the charger may be mid-download. The dividing line that makes a row untouchable by a **bulk deployment**: bulk leaves in-flight rows completely unmodified (reported as `skipped`), never resetting their attempt/retry state. A PENDING row with `attempt_count == 0` is *scheduled but not in-flight* and is safe to re-UPSERT. Force-restarting an in-flight charger is the single-charger path's job, not bulk's.
_Avoid_: treating "PENDING" alone as "in progress" — the attempt count is what distinguishes scheduled from active.

### Tariffs and pricing

**All-in tariff** / **All-inclusive tariff**:
Per-kWh price the operator types and the customer sees. Includes BOTH GST and the **Synthetic platform fee**. Stored on `Tariff.tariff_per_kwh_all_in`.
_Avoid_: incl-tax tariff, gross tariff, retail tariff.

**`rate_per_kwh`**:
Internal back-derived figure used by line-item billing math. Equals `all_in × (1 - fee_pct/100) / (1 + gst_pct/100)`. Never shown to customers.
_Avoid_: base rate, excl-tax tariff (both ambiguous post-2026-05-18).

### Fees and budget

**Synthetic platform fee**:
Fixed percentage (default 2%, set via `RAZORPAY_PLATFORM_FEE_PERCENT`) of `amount_paid` on a **QR Payment**. Used for budget cap, over-payment refund, and the invoice's gateway-charges line. Treated as all-in: commission = `× 2/118`, GST on commission = `× 2 × 18/118`.
_Avoid_: platform fee (overloaded), gateway fee (also overloaded).

**Actual platform fee**:
Razorpay's real deduction on a captured payment, sourced from the payment webhook or the Razorpay API. Stored on `QRPayment.platform_fee` / `razorpay_commission` / `razorpay_gst`. Used only for ops, reconciliation, and the drift detector — never for customer-facing math AND (post 2026-05-29) never for the franchisee settlement ledger either. See ADR 0001 amendment.
_Avoid_: real fee, captured fee.

**Budget cap**:
Redis-cached upper bound on energy a **QR Session** can deliver. Equals `(amount_paid - synthetic_fee) / (1 + gst_pct/100) / rate_per_kwh`. Enforced from the MeterValues handler by dispatching `RemoteStopTransaction` when consumption crosses the cap.
_Avoid_: limit, cap.

### Billing artefacts

**GST Invoice**:
A `GSTInvoice` row issued per billable charging session. Supplier is always VoltLync (merchant-of-record); the franchisee operator is captured as a snapshot block on the PDF (Razorpay disclosure requirement). Never issued for zero-energy sessions, internal-role sessions, or wallet top-ups.
_Avoid_: receipt, bill.

**Invoice Date**:
The legal date printed on a **GST Invoice**, and the basis for both its **Financial Year** and its serial number. Defined as the **issue instant** — when the `GSTInvoice` row is generated, i.e. session finalize (≈ StopTransaction) — expressed in **IST**, not UTC. This is the orthodox GST "date of issue"; because numbers are also allocated at issue, serial order and date order always agree. Server stores instants in UTC; IST is the derivation/presentation zone (the standing convention — see [[project-admin-ui-ist-server-utc]]). The session-*start* instant is shown separately as the "Charging date/time" (`charged_on`) and is informational only — it is **not** the invoice date. See [[adr-0012-gst-invoice-date-ist-issue-basis]] for the issue-vs-start and convert-on-read-vs-DATE-column rationale.
_Avoid_: charging date, session-start date (these name `charged_on`, a different field).

**Financial Year (FY)**:
Indian fiscal year, Apr–Mar, written `2026-27`. Derived from the **Invoice Date** (the issue instant in IST), and scopes the per-(franchisee, series) invoice serial sequence.
_Avoid_: calendar year, billing year.

### Settlements and payouts

**Settlement Entry**:
The per-**Charging Session** record of what a franchisee earned, one `CommissionLedgerEntry` row per billable session, created at session finalize. Carries `franchisee_payout` (the franchisee's take) net of `platform_commission` and `tds_amount`, alongside `gross_amount` and the session's `energy_consumed_kwh`. This is the unit the franchisee Settlements page lists and aggregates over.
_Avoid_: "settlement" unqualified (overloaded with the money-movement below), "commission" as a noun for the whole row (it's one field).

**Settlement Status**:
The lifecycle of *paying out* a **Settlement Entry** to the franchisee via Razorpay Route, tracked on `CommissionLedgerEntry.settlement_status`: `PENDING → TRANSFER_INITIATED → TRANSFER_PROCESSED → SETTLED`, with `FAILED`, `REVERSED`, `ON_HOLD`, `BELOW_THRESHOLD` as off-happy-path states. A **Settlement Entry** exists and counts as earned the moment the session finalizes; its **Settlement Status** is whether the money has reached the franchisee yet.
_Avoid_: conflating "earned" (the entry exists) with "settled" (the status reached its terminal state).

**Account balance (Razorpay float)**:
The money sitting in VoltLync's Razorpay account that has been captured but not yet swept to the bank — the spendable float Razorpay uses to fund **instant refunds** (`speed=optimum`) and Route payouts. Read live from `/v1/balance` (`balance`, in paise); the endpoint's `updated_at`/`last_fetched_at` fields are unmaintained junk but the value is real-time. **Drained by each settlement sweep**, so it trends toward zero between settlements regardless of transaction volume — a high-volume account that settles near-daily can still hold only a few hundred rupees. This is why large instant refunds intermittently downgrade to `normal`: the float is below the refund amount at that instant. Not the same as total unsettled or total transacted volume.
_Avoid_: "balance" unqualified (collides with **Wallet** balance), "unsettled amount" (related but not identical — fees, holds, and payouts also move it).

**Refund Credits**:
A prepaid Razorpay wallet, separate from the **Account balance (Razorpay float)**, that funds refunds independently of the settlement schedule — top it up in advance and instant refunds draw from it even when the float has been swept to bank. **Must be enabled by Razorpay before use; currently disabled** on the VoltLync account (`refund_credits=0`), so it provides no cushion today. The recommended fix for instant-refund downgrades.
_Avoid_: "refund balance", "refund wallet" (the canonical Razorpay term is Refund Credits).

### Observability

**OCPP message log**:
A row in the `log` table (`OCPPLog` model) capturing one inbound OCPP RPC call — BootNotification, Heartbeat, MeterValues, StatusNotification, etc. Direction, payload, correlation ID. Retained indefinitely for protocol-level audit.
_Avoid_: "log entry" (ambiguous with audit log), "OCPP event" (collides with NR event below).

**Audit event**:
A row in the `audit_log` table written via `log_audit_event(...)` capturing a domain action — `charger.connected`, `charger.disconnected`, `charger.connection_rejected`, etc. The supplier-of-record for "what did the system do" questions older than NR's retention window.
_Avoid_: "audit log" as a singular event term.

**NR custom event**:
A New Relic custom event recorded via `MetricsCollector.record_event(...)`. Operational telemetry only — disconnect lifecycle (`OCPPWebSocketDisconnect`), reject lifecycle (`OCPPWebSocketRejected`), transaction outcomes. Retained 8–30 days. Never the source of truth for billing, ledger, or compliance.
_Avoid_: "metric" (which is the 13-month numeric counter/gauge surface, a different thing).

**SignalQuality DataTransfer** / **Modem telemetry**:
A charger-emitted OCPP `DataTransfer` with `vendorId=VoltLync`, `messageId=SignalQuality`. The `data` field is a JSON string carrying `rssi`, `ber`, and (as of 2026-06-01) `temperature` — all modem-board-level values, sampled continuously and emitted even when no transaction is active. Stored per-**Charger** in the `signal_quality` table; see [[adr-0009-modem-temperature-in-signal-quality]] for why temperature lives here and not in `meter_value`.

**Known ambiguity**: the table name is a misnomer post-temperature. A future rename to `charger_telemetry` (or similar) is on the table but not blocking. Until then, treat `signal_quality` as the canonical home for any modem-emitted telemetry, not strictly signal-quality fields.
_Avoid_: confusing **Modem telemetry** with the (currently hypothetical) OCPP `Temperature` measurand sent inside `MeterValues.sampledValue`. The latter, if/when it appears, is per-transaction cable/socket/EV temperature and belongs on `meter_value` — see ADR 0009 "Consequences" for the orthogonality argument.

## Relationships

- A **Charging Session** is funded by either a **Wallet** (debit at finalize) or a **QR Payment** (prepaid, refund-on-finalize).
- **Funding source is determined at StartTransaction, not at initiation.** The `on_start_transaction` handler resolves the `User` by `rfid_card_id` (the idTag — the app's RemoteStart sends `user.rfid_card_id` as the idTag, so app-started and card-tapped sessions are indistinguishable at this layer), then: if a **QR Payment** links to the transaction it is a **QR Session**; otherwise, if the user has a **Wallet**, it is a **Wallet Session**. Consequence: nothing about *how* a session was triggered (app remote-start, deep-link API call, or local RFID tap) changes its funding — so any control that must prevent wallet-funded sessions has to act on this decision, not on the frontend.
- A **QR Payment** carries both an **Actual platform fee** (truth from Razorpay) and a **Synthetic platform fee** (policy, fixed). They are not expected to be equal; variance is absorbed entirely by VoltLync. Post 2026-05-29, both the **GST Invoice** gateway-charges line AND the **`commission_ledger_entry.pg_fee_amount`** use the Synthetic figure; the franchisee is shielded from Razorpay's instantaneous fee schedule.
- A non-zero-energy, non-internal **Charging Session** produces exactly one **GST Invoice**.
- A **Tariff** stores both `tariff_per_kwh_all_in` (display) and `rate_per_kwh` (math); writes update both, reads pick the one that fits the surface.
- The **Budget cap** is computed against the **Synthetic platform fee**, never the **Actual platform fee**, to give customers a predictable contract.

## Example dialogue

> **Dev:** "If Razorpay actually charges us 1.5% on a UPI payment, do we record it as the platform fee?"
> **Domain expert:** "Yes — the 1.5% lands in the **Actual platform fee** fields on the `QRPayment` row, for reconciliation. But the invoice's gateway-charges line and the budget cap both use the **Synthetic platform fee** of 2%, regardless. The 0.5% variance is VoltLync's P&L."

> **Dev:** "If a customer pays ₹500 and the charger reports zero kWh delivered, what's the refund?"
> **Domain expert:** "Full ₹500. **Zero-energy session** — no service rendered, no GST invoice issued, VoltLync absorbs Razorpay's processing fees as a loss."

> **Dev:** "Why is the all-in tariff displayed exactly ₹25 but the invoice line shows ₹24.50?"
> **Domain expert:** "The invoice's per-kWh rate is GST-only because the gateway fee is itemised as its own line. Adding the 2% into the per-kWh rate would double-count against the gateway line. Customer-facing displays show the **All-in tariff**; the invoice shows the components."

## Flagged ambiguities

- "platform fee" used to be overloaded for both the real Razorpay deduction and the policy figure — resolved 2026-05-18 by introducing **Actual platform fee** and **Synthetic platform fee** as distinct terms.
- "incl. tax" tariff was ambiguous after the gateway-fee policy change — resolved 2026-05-18 by retiring `tariff_per_kwh_incl_tax` in favour of **All-in tariff** (`tariff_per_kwh_all_in`), which explicitly includes both GST and the synthetic gateway fee.
