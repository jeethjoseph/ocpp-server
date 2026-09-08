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
A session funded by **one or more** UPI payments scanned from the charger's QR sticker; the user is a `UPI_GUEST` or a pre-existing user matched by phone/VPA. A single QR Session is still **one OCPP transaction** (one `Transaction` row, one `transaction_id`) — stacking multiple payments does not create multiple sessions (see [[stacked-qr-payment]] and [[adr-0021-stackable-qr-budget]]).
_Avoid_: guest session, anonymous session; assuming one QR Session ⇒ exactly one `QRPayment` (it is now **1:N** — see [[stacked-qr-payment]]).

**Stacked QR payment** / **QR budget top-up**:
An additional `QRPayment` made by the **same payer** (matched on `customer_vpa`, falling back to `customer_contact`/phone) against a charger that is **already CHARGING**, which **extends the QR Session's budget instead of being rejected**. Replaces the prior "charger busy ⇒ reject + full-refund" behavior *for the same payer only* — a **different** payer scanning a busy charger still gets reject + full-refund. The session's spendable budget is the **sum** of every linked payment's net amount (`amount_paid − gateway_fee`, the actual Razorpay fee per [[adr-0026-tariff-excludes-gateway-actual-fee]]); charging continues with **no StopTransaction** at the seam. Relationship `QRPayment → Transaction` is therefore **1:N** (one billable OCPP transaction funded by N payments), a deliberate relaxation of the old 1:1 (see [[adr-0021-stackable-qr-budget]]).
_Avoid_: "continuation transaction" / "segment" — there is exactly one `Transaction`; stacking tops up its budget, it does not spawn new transactions. _Avoid_: calling a different-payer concurrent payment a stack — that is still a rejected **concurrent payment**.

**LIFO refund allocation**:
The rule for returning a QR Session's **unused budget** (`Σ prepaid − actual cost`) across its stacked payments at StopTransaction: refund the **most recent** payment first, walking backward. Earlier payments are treated as consumed first, so each ends up fully consumed (no refund), fully unused (full refund), or — for at most one boundary payment — partially refunded. Minimises Razorpay refund calls and reuses the per-payment refund path + `qr_payment_{PK}` idempotency key. See [[adr-0021-stackable-qr-budget]].
_Avoid_: pro-rata splitting (partial refund on every payment — more calls/fees, no fairness gain since it is one payer).

**Non-billable Session**:
A session that produces **no GST invoice and no Settlement Entry** — for **QR Sessions** a full refund of `amount_paid`, for **Wallet Sessions** no debit. Per [[adr-0013-de-minimis-energy-waiver]] (**amended 2026-06-24**) there are exactly TWO such bands, keyed on `transaction_status` × energy:

- **Zero-energy Session** (`energy ≤ 0`, any status): no taxable supply occurred — nothing was delivered. See [[adr-0002-zero-energy-full-refund]].
- **Fault-refund Session** (`transaction_status = FAILED` and `0 < energy < 0.5 kWh`): the session terminated abnormally (`_fail_transaction_with_billing` — charger stopped without a clean StopTransaction, or socket-grace timeout) after delivering a trivial amount — the "intended a lot, faulted early" case. Full refund / no debit; the franchisee absorbs the trivial kWh.

A **COMPLETED** session that delivered any energy is **billable**: it bills from the **first Wh** (no cliff, no minimum-charge floor) and issues a GST invoice + Settlement Entry — the customer received the service and the franchisee earns the settlement.
_Avoid_: **De-minimis Session** — a **retired** term (2026-06-24). It used to mean a *waived* completed sub-0.5 session; those now **bill**. _Avoid_: conflating **Zero-energy** (non-supply, any status) with **Fault-refund** (FAILED + trivial delivery).

**Fault-refund ceiling** (`MIN_BILLABLE_ENERGY_KWH`):
The 0.5 kWh threshold below which a **FAILED** session is fully refunded (the **Fault-refund Session** band). A hardcoded `Decimal` constant (`MIN_BILLABLE_ENERGY_KWH = Decimal("0.5")`), not an env var — changing it goes through code review + ADR. Keyed on **energy** (`energy_consumed_kwh`), never power. **Post-2026-06-24 it no longer gates billing** — COMPLETED sessions bill from the first Wh; the constant now only bounds the FAILED-session fault refund, so the variable name is a partial misnomer (kept to avoid churn).
_Avoid_: "minimum billable energy" / "minimum charge" as if completed sessions below 0.5 kWh are free — they bill.

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

`charge_point_string_id` is a **UUID4 generated at onboarding** and is **internal-only** — it is the OCPP WSS path segment *and* the Basic Auth **username** under [[adr-0020-charger-websocket-basic-auth]], so it is never rendered on a customer-facing surface. Customers see the **Asset Code** instead.
_Avoid_: showing `charge_point_string_id` to customers; calling it "the charger ID" without qualification (that phrase is overloaded across `Charger.id`, `charge_point_string_id`, and `GSTInvoice.charger_id_str`).

**Asset Code**:
The customer-facing identifier for a **Charger**: an environment series plus a zero-padded integer — `VOW0001` production, `VOWS0001` staging and development. Regex `^VOWS?\d{4,}$`, minimum width four and widening by itself past `VOW9999`, stored `VARCHAR(12)`. Unique across VoltLync **and across environments**: the series comes from `CHARGER_CODE_SERIES` in the git-tracked `backend/policy.py`, keyed on the existing `ENVIRONMENT` var, and an unrecognised value resolves to `VOWS`, never `VOW`, so a misconfigured box cannot mint a production-looking code. The split exists because **staging serves real paying customers** (~11 GST invoices/day as of 2026-08) — the same cross-environment hazard that produced duplicate `VL/F2/` invoice numbers and the `qr_payment_{PK}` refund collision.

It names the **physical unit**, not a position: it follows the hardware through a station re-parent, and a replacement unit brings its own code rather than inheriting the dead one's. **Stored, not derived** (`Charger.asset_code`, `UNIQUE NOT NULL`): it derives from nothing mutable, so the anti-drift rule behind [[adr-0015-ocpi-identity-scheme]] has nothing to bite on. **System-allocated, never typed** — the server assigns `max + 1` at creation and there is no admin-editable field, which makes uniqueness structural rather than a form-validation problem. Bears **no relationship to `Charger.name`**, which stays free-form, nullable and non-unique; the one-time backfill seeds from the `VOW####` stencils already painted on the fleet so existing labels stay valid, and nothing reads `name` afterwards. **Allocation is strictly monotonic** — never reused, gaps never backfilled, so nobody has to reason about whether a hole is safe.

Looked up by **parsing the integer**, not matching the string: `VOW0001`, `VOW00001` and `vow1` all resolve, while a foreign series is rejected rather than coerced. That is what makes the minimum-width rule safe: a code typed at one padding resolves at any other. Rendered as `CHARGER: VOW0001`; the customer-service phrasing is "the charger marked VOW0001". Snapshotted onto a **GST Invoice** at issue (`charger_id_str`). See [[adr-0028-customer-facing-charger-code]].
_Avoid_: "charger ID" / "charge point ID" (those name the UUID **OCPP identity**), "bay number" or "slot" (the code names a unit, not a position — a **Bay** was considered and rejected), treating it as enterable input on a customer surface.

**Charger Purpose**:
What a **Charger** is *for*, as `Charger.purpose` — `PUBLIC` (advertised, billable, invoiceable), `PRIVATE` (real hardware and real billing, not advertised) or `TEST` (bench, pre-handover or internal; **Internal-role Sessions** only, never billed, never invoiced). Defaults to `PUBLIC`, which is the load-bearing choice: a row missed in any backfill keeps working rather than blocking customers, so the failure direction is fail-open. Deliberately **one enum, not two booleans** — every test unit is non-public, so `is_test` + `is_public` would admit a bench unit advertised as bookable, and the behaviours do not decompose anyway (`TEST` gates billing, `PRIVATE` gates only visibility).

Deliberately **not** encoded in the **Asset Code**: purpose is mutable — a bench unit can be promoted to fleet — and an identifier must not change when a mutable attribute does. Also distinct from `availability` ([[adr-0008-charger-availability-separate-from-status]]), which is admin-commanded intent on *serviceable* hardware; marking a bench unit `Inoperative` would conflate "temporarily withdrawn" with "not fleet hardware at all".
_Avoid_: "disabled", "hidden" (both describe one effect of one value); reusing `availability` or `latest_status` to mean any of this.

**Documented exception to the Asset Code avoid-list:** `GSTInvoice.charger_id_str` keeps its name. The column predates the term and is a header in the **GST filings CSV export** (`routers/invoices.py`), which feeds an accountant's spreadsheet — renaming it would silently break saved import mappings on a compliance surface. It holds an **Asset Code** for invoices issued after the cutover and a legacy `charge_point_string_id` UUID before it; the two eras are separable by `^VOWS?\d{4,}$`. It is a snapshot of "the charger identifier printed on this invoice", which stays true across the format change.

Its two siblings are **internal, never printed and never exported** to the GST filings CSV: `charger_station_id` (the station at issue, so a compliance query needs no regex) and `charger_ocpp_id` (the **OCPP identity** UUID, the audit link to the physical unit). Prefer either of those, or the `transaction` FK, when joining an invoice back to hardware — an **Asset Code** does name a specific unit, but an admin can correct it and the snapshot cannot be corrected.

**Connector**:
A physical plug on a `Charger`, modelled as a `Connector` row. **Working invariant (2026-05-21):** every `Charger` in our fleet has exactly one `Connector` (= one OCPI EVSE). The data model permits N:1 but no current deployment uses it, and no per-connector OCPP state is tracked. Carries `max_power_kw` plus the OCPI-native columns (`ocpi_standard`, `ocpi_format`, `ocpi_power_type`, `max_voltage`, `max_amperage`) that are the **source of truth for the [[ocpi-feed]]** (see [[adr-0016-connector-ocpi-normalization]]).

**Plug type** / **Connector type**:
`Connector.connector_type` — a `ConnectorTypeEnum` (`Type2`, `Type1`, `Socket`, `CCS`, `CHAdeMO`, `GB/T`, `domestic`; enum-enforced since 2026-07-23, previously free text). It is **load-bearing on two orthogonal physical axes**, declared per-type in `charger_type_service.CONNECTOR_TRAITS` (see [[adr-0027-per-connector-type-suspend-windows]]):
- `starts_from_available` — no Control Pilot signal ⇒ the charger idles in `Available` and remote start is allowed from `Available` as well as `Preparing` (`Socket`, `domestic`, `Type1`, `Type2`). The shared `startable_statuses` helper is the ONLY start-gate implementation.
- `latching` — the cable locks into the vehicle inlet ⇒ a disconnected session is held for the LONG suspend window (`Type1`, `Type2`, `CCS`, `CHAdeMO`, `GB/T`); unlatched sockets get the short window. **Type2 is why these are two axes**: socket-like on the start gate, latched on the window.
Unknown types resolve to the safe side of both axes (Preparing-only, short window). For the [[ocpi-feed]], `ocpi_standard` remains the source of truth (see [[adr-0016-connector-ocpi-normalization]]).
_Avoid_: "connector" as a customer-facing label when you mean "charger of plug type X". Renamed in the public station modal 2026-05-21 to avoid the conflation.

**Suspend window**:
How long a mid-session charger disconnect (or reboot) is held `SUSPENDED` awaiting reconnect before force-finalize. **Per-connector-type, keyed on the `latching` trait: 12h latched / 45min unlatched** — values in the git-tracked `backend/policy.py`, NOT env vars (see [[adr-0027-per-connector-type-suspend-windows]]). The same window applies on BOTH suspension paths: the disconnect timer and the post-boot timer armed by BootNotification (the old 300s post-boot timer is retired — a reboot must never shorten the promised grace window). The stale-suspended sweep and resume-staleness guard derive their cutoffs per-transaction (window + 60s buffer), preserving the [[adr-0022-resume-staleness-threshold-derived]] invariant per-row.

### Charger connection security

**Charger Auth Key**:
**Status (2026-08-18): partially shipped.** The key and its `Charger.auth_key_hash` column are being introduced by [[adr-0029-diagnostic-bundle-authenticated-https-upload]] to authenticate **Diagnostic Bundle** uploads over HTTPS. The OCPP WebSocket handshake described below is still **unauthenticated** — [[adr-0020-charger-websocket-basic-auth]] remains PROPOSED. Read the rest of this entry as the target design for the WSS half.

The per-`Charger` secret that authenticates the OCPP WebSocket connection under **OCPP 1.6 Security Profile 2** (WSS transport + HTTP Basic Auth). A 20-byte random key; the charger presents it as the Basic Auth **password** with the `charge_point_string_id` as the **username** on the WSS upgrade. The server stores only a **SHA-256 hash** (`Charger.auth_key_hash`), never the plaintext — the plaintext is revealed exactly once at provisioning/rotation and loaded onto the unit by charger-side tooling (delivery is out of scope for the server). Lost key ⇒ rotate, never retrieve. SHA-256 (not bcrypt) is deliberate: the key is a high-entropy machine credential checked on every reconnect, so a fast hash is both sufficient and cheaper for flaky-modem reconnect churn. See [[adr-0020-charger-websocket-basic-auth]].
_Avoid_: "charger password" (implies a low-entropy human secret and the wrong hashing choice); conflating it with **AuthorizationKey** (the OCPP config key the charger-side tool writes locally) — same value, different side.

**Charger auth enforcement**:
The rule deciding whether a connection is required to present a valid **Charger Auth Key**. **Per-charger**, keyed on `auth_key_hash` presence: null ⇒ *legacy mode* (connection allowed, logged as `charger.connection_insecure` — the migration burn-down signal); non-null ⇒ *enforced* (valid Basic Auth required, **username must equal the path `charge_point_id`**, else close `1008`). Auth is checked **before** the force-disconnect-stale-connection logic so an unauthenticated caller can never kick a live charger offline. Once the insecure count reaches zero fleet-wide, the global `REQUIRE_CHARGER_AUTH` flag closes the window by rejecting even null-hash chargers. See [[adr-0020-charger-websocket-basic-auth]].
_Avoid_: "big-bang cutover" — enforcement is intentionally per-charger to avoid a flag-day outage across flaky-modem fleet.

### Remote commands

**Remote command**:
An OCPP RPC this server initiates *towards* a charger over the open WebSocket — `RemoteStartTransaction`, `RemoteStopTransaction`, `Reset`, `ChangeAvailability`, `UpdateFirmware`, `DataTransfer`. Always server→charger. The charger's own calls (BootNotification, MeterValues, StatusNotification, …) are not remote commands; those land on the **OCPP message log**.

**Command outcome**:
What a **remote command** produced, as three mutually exclusive states: **Accepted** (the charger committed to act), **Refused** (the charger answered and declined), **Unanswered** (no reply inside the 30-second window). A charger that is not connected at all never produces a command outcome — connectivity is a pre-flight check answered before anything is sent.
`Accepted` deliberately absorbs OCPP's `Scheduled` (`ChangeAvailability` only — "I will act when the current session ends"), because both are commitments to act and the one caller that sees `Scheduled` already treats it identically. The raw wire status stays reachable for callers that surface it verbatim.
_Avoid_: "command result" — `CallResult` is already the OCPP messageTypeId-3 ack frame. "Success"/"failure" for the pair — a refusal is neither: the system worked correctly and the answer was no.

**Refused** vs **Rejected**:
Two different actors saying no, deliberately kept apart. **Refused** is the *charger* declining a **remote command**. **Rejected** is *this server* declining something — most visibly the `OCPPWebSocketRejected` **NR custom event** for a connect-time reject. The OCPP wire value for a charger's no is literally `"Rejected"`; it is translated to **Refused** at the transport boundary so the actor is unambiguous everywhere above it.
_Avoid_: "rejected" for a charger's answer — it inverts the actor relative to the connect-time event of the same name.

### External interoperability (OCPI)

**OCPI feed**:
The standards-compliant **OCPI 2.2.1** (Open Charge Point Interface) CPO endpoint VoltLync exposes so external consumers — Google Maps (via `EVCS-global@google.com`), aggregators, and roaming hubs — can pull static **Location** data and real-time EVSE status. A **direct CPO feed** (no aggregator middleman), served from the same FastAPI app under `/ocpi/cpo/2.2/` (modules: Versions + Credentials + Locations; Tariffs deferred to phase 2), behind OCPI token auth (not Clerk), gated by `OCPI_ENABLED`. Google accepts **only** OCPI for EV charging data and requires Real-Time Availability (RTA). Both envs serve, kept distinct by an **env-specific `party_id`** (`VLT` prod / `VLS` staging); staging is a deliberate **pre-rollout canary** for chargers already live on Google. See [[adr-0015-ocpi-identity-scheme]].
_Avoid_: "GELFS feed" (Google's legacy proprietary spec, superseded by OCPI for onboarding), "Google feed" (OCPI is the substrate; Google is one consumer).

**Published charger**:
A `Charger` with `publish_to_google = true` — the per-EVSE flag that gates [[ocpi-feed]] inclusion (a Location is published iff it has ≥1 published EVSE). The toggle to `true` is **completeness-gated** (requires `ocpi_evse_id` + station coords/city/address + connector `ocpi_standard`) and **audit-logged**, because publishing has irreversible-in-identity side effects: unpublishing removes the Google POI, but the `evse_id` is permanently spent and is never rebound to a different physical charger (see [[adr-0015-ocpi-identity-scheme]]).
_Avoid_: conflating "published" (visible on Google) with the **OCPI EVSE status** `AVAILABLE` (live state) — a published charger can be `CHARGING`, `UNKNOWN`, etc.

**OCPI EVSE status**:
The single live status value OCPI exposes per EVSE (`AVAILABLE`, `CHARGING`, `BLOCKED`, `RESERVED`, `INOPERATIVE`, `OUTOFORDER`, `REMOVED`, `UNKNOWN`). It is a **fusion**, in strict priority order, of THREE inputs: admin `Charger.availability` (intent, per ADR 0008) → online/offline (Redis-connected + `last_heart_beat_time` ≤ 120s) → `Charger.latest_status` (OCPP-reported live state). Admin `Inoperative` wins over everything (→ `INOPERATIVE`); an **offline** charger is `UNKNOWN` (not `OUTOFORDER` — disconnection ≠ fault, given flaky Quectel modems); otherwise `latest_status` maps through (`FAULTED`→`OUTOFORDER`, `UNAVAILABLE`→`INOPERATIVE`, `RESERVED`→`RESERVED`, all occupied states `PREPARING/CHARGING/SUSPENDED_*/FINISHING`→`CHARGING`, `AVAILABLE`→`AVAILABLE`). A charger is **never dropped** from the feed by status — removal churns the Google POI (see [[adr-0015-ocpi-identity-scheme]]).
_Avoid_: mapping OCPI status from our **`availability`** field alone (it's admin intent only) or from **`latest_status`** alone (it ignores admin override and offline state). Note the term collision: OCPI says "status" for the live state; our `ChargerAvailabilityEnum` is named "availability" but means admin intent — they are NOT the same axis.

### Firmware

**Firmware deployment** / **Deploy**:
The admin action of scheduling a firmware version onto one or more **Chargers**. A deployment creates or resets a `FirmwareUpdate` row to PENDING per charger; the background scheduler later dispatches the OCPP `UpdateFirmware`. A **bulk deployment** is the same action applied to a multi-selected set of chargers from the **Firmware Library**, scoped by the picker's current filter (e.g. one station, or "all not already on this version").
_Avoid_: "push", "flash" as the canonical verb (fine informally; "deploy" is the term).

**In-flight firmware update**:
A `FirmwareUpdate` row that is PENDING with `attempt_count > 0` — the server has already dispatched at least one `UpdateFirmware` and the charger may be mid-download. The dividing line that makes a row untouchable by a **bulk deployment**: bulk leaves in-flight rows completely unmodified (reported as `skipped`), never resetting their attempt/retry state. A PENDING row with `attempt_count == 0` is *scheduled but not in-flight* and is safe to re-UPSERT. Force-restarting an in-flight charger is the single-charger path's job, not bulk's.
_Avoid_: treating "PENDING" alone as "in progress" — the attempt count is what distinguishes scheduled from active.

### Tariffs and pricing

**Tariff** / **GST-included rate**:
The GST-inclusive, **gateway-exclusive** per-kWh energy price the operator types and the customer sees on QR/stations/map screens. Stored on `Tariff.rate_gst_included` — the operator-typed **source of truth**. The gateway is **not** part of the Tariff; it is a separate **Gateway fee** line disclosed at payment/invoice time.
_Avoid_: all-in tariff, all-inclusive tariff (retired 2026-07-13 — the gateway is no longer folded in), incl-tax tariff, gross tariff.

**Base rate**:
The GST- and gateway-exclusive per-kWh energy price, **back-calculated** from the **Tariff** as `rate_gst_included / (1 + gst_pct/100)` and stored on `Tariff.rate_per_kwh` (retained column). Drives line-item billing (`energy_cost = kWh × base_rate`) and is shown as the "Rate" of the Energy line on the itemised **GST Invoice**. A constant per tariff — never varies per bill. See [[adr-0026-tariff-excludes-gateway-actual-fee]].
_Avoid_: rate_per_kwh (that is the column name; "base rate" is the domain term — promoted from the avoid-list 2026-07-13), excl-tax tariff.

### Fees and budget

**Gateway fee**:
Razorpay's actual processing charge on a captured **QR Payment**, as reported by the `qr_code.credited` webhook, sized on `amount_paid` (the full prepay). A **customer-borne, separate line** on the **GST Invoice** — never folded into the **Tariff** — and reserved out of the **Budget cap**. Often ₹0 in practice (UPI P2M ≤ ₹2000 is zero-MDR per NPCI/RBI), but never *assumed* zero — the webhook value is authoritative. Because it is passed through (added to what the customer pays, subtracted in both refund and settlement), it **cancels out of the franchisee's payout**. Stored on `QRPayment.platform_fee` / `razorpay_commission` / `razorpay_gst`. Known drift: the webhook value can over-state the settled fee for zero-MDR UPI ([[known-issues]] #1); VoltLync accepts the small customer-refund residual.
_Avoid_: synthetic platform fee (retired 2026-07-13 — the fee is the actual webhook figure now), assumed fee, platform fee (was overloaded).

**Budget cap**:
Redis-cached upper bound on energy a **QR Session** can deliver. Equals `(amount_paid − gateway_fee) / (rate_per_kwh × (1 + gst_pct/100))`, using the **actual Gateway fee** reserved at StartTransaction (₹0 for zero-MDR UPI). Enforced from the MeterValues handler by dispatching `RemoteStopTransaction` when consumption crosses the cap.
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
The row **stores** `gross_amount`, but the **franchisee portal deliberately does not surface it** (2026-07-01) — a franchisee sees **Payout**, **TDS**, **commission %**, and **Power Consumed (kWh)**, never platform Gross. Gross is a platform-level figure for admin/reconciliation only; the franchisee's economic story is payout-per-energy-delivered. The franchisee settlements endpoint therefore omits `gross_amount`/`total_gross` from its response.
_Avoid_: "settlement" unqualified (overloaded with the money-movement below), "commission" as a noun for the whole row (it's one field). _Avoid_: surfacing **Gross** on any franchisee-facing surface (table, summary, graph, export).

**Settlement Status**:
The lifecycle of *paying out* a **Settlement Entry** to the franchisee via Razorpay Route, tracked on `CommissionLedgerEntry.settlement_status`: `PENDING → TRANSFER_INITIATED → TRANSFER_PROCESSED → SETTLED`, with `FAILED`, `REVERSED`, `ON_HOLD`, `BELOW_THRESHOLD` as off-happy-path states. A **Settlement Entry** exists and counts as earned the moment the session finalizes; its **Settlement Status** is whether the money has reached the franchisee yet.
_Avoid_: conflating "earned" (the entry exists) with "settled" (the status reached its terminal state).

**Account balance (Razorpay float)**:
The money sitting in VoltLync's Razorpay account that has been captured but not yet swept to the bank — the spendable float Razorpay uses to fund **instant refunds** (`speed=optimum`) and Route payouts. Read live from `/v1/balance` (`balance`, in paise); the endpoint's `updated_at`/`last_fetched_at` fields are unmaintained junk but the value is real-time. **Drained by each settlement sweep**, so it trends toward zero between settlements regardless of transaction volume — a high-volume account that settles near-daily can still hold only a few hundred rupees. Low float is **one** cause of an instant refund downgrading to `normal` (when the float is below the refund amount). Not the same as total unsettled or total transacted volume.
**Correction (2026-07-01):** low float is NOT the only — nor the observed primary — cause of `speed=optimum` downgrades. Razorpay confirmed in writing (ticket #19564492) that the downgrades VoltLync actually hit were caused by their **opaque, non-configurable fraud shield rules** — specifically a **per-VPA instant-refund limit inside a 24-hour window** plus a **soft-failure-then-retry-pinned-to-normal** behavior — with no merchant visibility or control. Do NOT diagnose the next downgrade as a float problem by default; the risk-engine cause is provider-side and invisible from `/v1/balance`. This opacity is the driver for evaluating a Paytm migration.
_Avoid_: "balance" unqualified (collides with **Wallet** balance), "unsettled amount" (related but not identical — fees, holds, and payouts also move it).

**Refund Credits**:
A prepaid Razorpay wallet, separate from the **Account balance (Razorpay float)**, that funds refunds independently of the settlement schedule — top it up in advance and instant refunds draw from it even when the float has been swept to bank. **Must be enabled by Razorpay before use; currently disabled** on the VoltLync account (`refund_credits=0`), so it provides no cushion today. Fixes only the **float** cause of instant-refund downgrades — it does **NOT** address the **fraud-shield / per-VPA 24h** downgrades Razorpay confirmed in ticket #19564492 (see the correction on **Account balance (Razorpay float)**). So it is a partial cushion, not a complete fix for the downgrades VoltLync has actually experienced.
_Avoid_: "refund balance", "refund wallet" (the canonical Razorpay term is Refund Credits).

### Observability

**OCPP message log**:
A row in the `log` table (`OCPPLog` model) capturing one inbound OCPP RPC call — BootNotification, Heartbeat, MeterValues, StatusNotification, etc. Direction, payload, correlation ID. Retained ~90 days (`RETENTION_DAYS`, default 90), then batch-deleted by the `DataRetentionService` cleanup job — a rolling protocol-level audit window, **not** a permanent archive.
_Avoid_: "log entry" (ambiguous with audit log), "OCPP event" (collides with NR event below).

**OCPP Action**:
The OCPP RPC name on an **OCPP message log** row — `BootNotification`, `StatusNotification`, `MeterValues`, `Heartbeat`, `StartTransaction`, etc. The primary filter dimension on the **Logs Console**, stored in the `OCPPLog.message_type` column. **Forward-only (2026-06-24):** the ingestion adapter writes the Action into `message_type` for CALL frames; CALLRESULT/CALLERROR ack frames carry the literal `CallResult`/`CallError`; unparseable/protocol-error frames carry an `OCPP` sentinel. **Historical rows ingested before this fix all carry `OCPP`** (the column was hardcoded), so the Action filter only matches rows newer than the fix — older rows age out via the 90-day retention window. No backfill (see `.scratch/logs-console/issues/06-populate-message-type-with-ocpp-action.md`, [[adr-0014-logs-console-bounded-query-surface]]).
_Avoid_: "message type" for the action name — it collides with the OCPP spec's own *message type* (the `messageTypeId` at `payload[0]`: `2 = Call`, `3 = CallResult`, `4 = CallError`), a separate orthogonal facet that pairs with **direction**, not the action filter. UI labels say "Action", never "Type".

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

**Diagnostic Bundle**:
A body of **charger-side firmware debug traces** — boot messages, state-machine transitions, modem/AT failures, relay actuations, vendor fault detail — buffered in the charger's on-board EEPROM and uploaded periodically to the CSMS over **HTTPS POST**, outside the OCPP channel. Deliberately and strictly **non-metering**: no kWh, no meter readings, no tamper or calibration events. That exclusion is what keeps a Bundle disposable observability data rather than legal-metrology data adjacent to a **GST Invoice**.

Newline-delimited UTF-8 records and nothing else. It carried a header of counters (`boot`, `seq`, `first`, `last`, `overflow`) until [[adr-0030-diagnostic-bundle-body-is-the-contract]] deleted it: every field required the charger to persist a counter across a reboot, which the hardware cannot do. **The body is the whole contract.** The CSMS reads three in-band markers from it — `===== BOOT`, `TIME_SYNC boot_ms=… utc=…`, and the ring-wrap line — and derives identity, time and loss from those. It is therefore *not* opaque: it is vendor-defined in content but parsed for delivery meaning, though never for domain meaning. Uploaded to `POST /api/diagnostics/bundles` under HTTP Basic Auth with the **Charger Auth Key**, and stored in S3; see [[adr-0029-diagnostic-bundle-authenticated-https-upload]].

_Avoid_: **Diagnostics** / **GetDiagnostics** as if this were the OCPP mechanism — it deliberately is **not** (see the ADR). _Avoid_: "charger logs" unqualified, which collides with **OCPP message log** (that is CSMS-observed protocol traffic; a Bundle is the charger's own internal trace, which the CSMS otherwise never sees). _Avoid_: treating a Bundle as a source of truth for energy — `MeterValues` / `StopTransaction` are the audited billing path, and a second unaudited copy would be a liability, not an asset. _Avoid_: **bundle sequence** and **epoch** — both are retired; a Bundle is identified by the **content digest** of its records. _Avoid_: describing a Bundle as "opaque", which was true only while the CSMS ignored its contents.

**Loss window**:
The span between one Diagnostic Bundle's last record and the next one's first, measured in **UTC reconstructed from in-band `TIME_SYNC` anchors**. Silence longer than a configured threshold is the signal that records went missing. Derived at read time, never stored — a delayed bundle can arrive later and fill the hole.

Replaces the record-number gap and overflow delta of [[adr-0029-diagnostic-bundle-authenticated-https-upload]], which needed counters the charger cannot keep. **Resolution is minutes, not records**, and the **cumulative count of records a charger destroyed before delivering them is no longer obtainable at all** — that needed a monotonic counter held separately from the data it describes. A **ring-wrap event** says overwriting is happening now; nothing says how much. Do not present either as a total. See [[adr-0030-diagnostic-bundle-body-is-the-contract]].
_Avoid_: **gap records** / **overflow delta** — both retired with the header.

**Reservation** (Diagnostic Bundle):
An index row written **before** its S3 object, carrying a null `archived_at`. It exists so a failed upload cannot strand an object no row points at — the ordering that produced 195 unreclaimable objects on staging in one morning. A reservation is **not a delivery**: it is invisible to the duplicate check, so a charger retrying is told to re-send rather than falsely assured the CSMS holds its records. `archived_at` is set only once the S3 put returns.

### Admin transactions console

**Transactions Console**:
The unified admin page at `/admin/transactions` listing **Charging Sessions** across *all funding sources and all statuses* in one place (the page the long-dead "Transaction Monitoring" landing-card link finally points to). It is a **convenience/triage view over Charging Sessions** — the `Transaction` model is the spine — not a new ledger or abstraction. Backed by the pre-existing `GET /transactions` endpoint, enriched per row with funding source and the backing payment record's status.
_Avoid_: treating it as a money ledger or a unified super-feed of payments/refunds/settlements — that was explicitly *not* chosen (see below).

**Two truthful status axes** (deliberately NOT collapsed into one derived status):

- **Session Status**: the native `TransactionStatusEnum` (STARTED…RUNNING…COMPLETED, CANCELLED, FAILED, BILLING_FAILED) — the session lifecycle.
- **Payment Status**: the **actual, native** status of the session's backing payment record — the real `QRPaymentStatusEnum` value (PAID…REFUNDED, **REFUND_FAILED**, EXPIRED) for a **QR Session**. **Effectively QR-only**: a **Wallet Session**'s money event is a `CHARGE_DEDUCT` row which carries *no* status enum (only TOP_UPs do), so wallet and **Internal-role** rows show blank (`—`) rather than a derived label — the wallet money outcome is already fully expressed by **Session Status** (COMPLETED = debited, BILLING_FAILED = billing failed) plus the amount. Shown verbatim; **never** projected into a synthesised cross-funding enum, and **never** derived for wallet just to fill the cell.

**Funding Source** (here): a multi-select filter / column on the console — `QR` / `Wallet` / `Internal` — derived per session via the existing `_resolve_funding` helper. It disambiguates which native vocabulary a row's **Payment Status** belongs to.
_Avoid_: a derived/canonical "PaymentStatus" projection spanning QR+Wallet — considered and **rejected** (lossy on exactly the mixed-state rows admins most need to triage; truthful native statuses + a funding-source filter is the convenience instead).

### Admin logs console

**Logs Console**:
The admin page at `/admin/logs` listing **OCPP message log** rows across *all chargers* in one filterable, URL-shareable place. A convenience/triage view over the `log` table — the same doctrine as the **Transactions Console**, not a new ledger or abstraction. Backed by `GET /api/admin/logs`. **Charger** is one optional filter (single-select, searchable); **OCPP Action** is the primary filter (multi-select); **direction** (IN/OUT) and **status** (SUCCESS/error) refine the fetched window. The charger detail page deep-links here pre-filtered (`?charger=<id>`) rather than embedding its own log viewer — the old per-charger embedded viewer and its `/logs/charger/{id}` endpoint are retired.
_Avoid_: "log viewer", "log page" — the canonical term is **Logs Console**, parallel to **Transactions Console**.

### Admin reports

**Report**:
A read-only, admin-only analytical view under `/admin/reports`, computed **live on request** — there is no stored/materialized snapshot and no server-side cache. Each report is a single endpoint that runs its aggregation against Postgres and returns a plain payload. The "don't recompute until asked" behaviour lives entirely on the client (TanStack Query `staleTime: Infinity` + an explicit **Refresh** button); **"last refreshed X ago" is the client's fetch time (`dataUpdatedAt`), not a server timestamp** — it is therefore per-viewer, not a shared team-wide snapshot. This was a deliberate choice over a cached snapshot table after measuring the cost (see [[adr-0025-live-uncached-admin-reports]]).
_Avoid_: "dashboard" (that word is taken by the operational landing page at `/admin`), "snapshot"/"cached report" (there is none — the numbers are always live at fetch time).

**Churn Report**:
The first **Report**, at `/admin/reports/churn`. A retention **cohort** analysis of **QR** customers: rows are the cohort of customers whose *first* successful **QR Payment** fell in a given period, columns are periods-since-first, cells are the share of that cohort who paid again. **Customer identity is `COALESCE(customer_vpa, customer_contact)`** on `qr_payment` (the same key the parked `analytics/refund_churn/` study uses) — QR customers are keyed by UPI handle / phone, not by `User` row. Grain is switchable **weekly (default) or monthly**; monthly is the more honest read because charging cadence is monthly, so weekly buckets scatter returners and understate retention. **Periods are IST calendar periods** (`date_trunc(... AT TIME ZONE 'Asia/Kolkata')`) — a boundary is an IST midnight, not a UTC one, so a charge just after IST-midnight isn't misfiled into the prior period. A customer counts from their **first captured payment** (statuses PAID/CHARGING/COMPLETED/REFUNDED); a **fully-refunded-only** customer is still counted (an engaged customer at ₹0 net). Backed by `GET /api/admin/reports/qr-churn`.
_Avoid_: treating the cohort as `User`-keyed (it is not — appless QR customers are often not `User` rows), reading the small-cohort percentages as precise (cohorts are tens of customers; the shape is signal, the decimals are noise), or assuming the customer count is exact — the `vpa`-then-`contact` key double-counts a customer who pays via both.

## Relationships

- A **Charging Session** is funded by either a **Wallet** (debit at finalize) or a **QR Payment** (prepaid, refund-on-finalize).
- **Funding source is determined at StartTransaction, not at initiation.** The `on_start_transaction` handler resolves the `User` by `rfid_card_id` (the idTag — the app's RemoteStart sends `user.rfid_card_id` as the idTag, so app-started and card-tapped sessions are indistinguishable at this layer), then: if a **QR Payment** links to the transaction it is a **QR Session**; otherwise, if the user has a **Wallet**, it is a **Wallet Session**. Consequence: nothing about *how* a session was triggered (app remote-start, deep-link API call, or local RFID tap) changes its funding — so any control that must prevent wallet-funded sessions has to act on this decision, not on the frontend.
- A **QR Payment**'s **Gateway fee** (actual, webhook-reported) is a customer-borne pass-through: it is added to what the customer pays and subtracted in both the refund and the settlement ledger, so it **cancels out of the franchisee's payout** — the franchisee's pool is `energy_kWh × base_rate`, independent of Razorpay's fee. Both the **GST Invoice** gateway line and **`commission_ledger_entry.pg_fee_amount`** use this actual figure (reverses the 2026-05-29 synthetic-ledger amendment; safe because the fee now cancels).
- A **billable**, non-internal **Charging Session** produces exactly one **GST Invoice** and exactly one **Settlement Entry**. Billable = delivered `energy > 0` AND not a **Fault-refund Session** — i.e. any **COMPLETED** session with energy (from the first Wh), or a **FAILED** session with `energy ≥ 0.5 kWh`. A **Non-billable Session** (Zero-energy, or FAILED + sub-0.5) produces neither. See [[adr-0013-de-minimis-energy-waiver]] amendment.
- A **Tariff**'s source of truth is the **Base rate** (`rate_per_kwh`); the displayed GST-inclusive **Tariff** is `base_rate × (1 + gst%)`, and the **Gateway fee** is never part of it.
- The **Budget cap** reserves the **actual Gateway fee** (₹0 for zero-MDR UPI), computed at StartTransaction, so a session's final refund can never go negative.

## Example dialogue

> **Dev:** "A ₹100 UPI QR payment — the webhook says the fee is ₹2, but UPI P2M under ₹2000 is zero-MDR. What do we charge the customer?"
> **Domain expert:** "We bill the webhook value as the **Gateway fee** — it's the only per-payment signal we have at billing time, and some payments genuinely do carry a fee. It sits as its own line on the invoice, separate from the energy **Tariff**. For a zero-MDR payment the settled fee turns out to be ₹0, so the customer is over-refunded by the webhook amount — a small residual we accept ([[known-issues]] #1). The franchisee is untouched either way; the fee cancels out of their payout."

> **Dev:** "If a customer pays ₹500 and the charger reports zero kWh delivered, what's the refund?"
> **Domain expert:** "Full ₹500. **Zero-energy session** — no service rendered, no GST invoice issued, VoltLync absorbs Razorpay's processing fees as a loss."

> **Dev:** "The operator typed ₹11.80 for the tariff, but the invoice's Energy line shows a rate of ₹10.00. Which is right?"
> **Domain expert:** "Both. ₹11.80 is the **Tariff** — the GST-inclusive energy price the operator sets and the customer sees. We back-derive the **Base rate** of ₹10.00 (`11.80 / 1.18`) for the invoice's Energy line, which is taxed separately. Neither number contains the gateway; the **Gateway fee** is its own line, shown only when a fee actually applies."

## Flagged ambiguities

- "platform fee" used to be overloaded for both the real Razorpay deduction and the policy figure — resolved 2026-05-18 by introducing **Actual platform fee** and **Synthetic platform fee** as distinct terms.
- "incl. tax" tariff was ambiguous after the gateway-fee policy change — resolved 2026-05-18 by retiring `tariff_per_kwh_incl_tax` in favour of **All-in tariff** (`tariff_per_kwh_all_in`), which explicitly includes both GST and the synthetic gateway fee.
- **"all-in tariff" and "synthetic platform fee" retired 2026-07-13.** The gateway is no longer folded into the tariff: the **Tariff** is now GST-inclusive but **gateway-exclusive** (energy only), and the **Gateway fee** is the *actual* webhook-reported Razorpay charge shown as a separate customer-facing line. "Base rate" was promoted from the avoid-list to the canonical term for `rate_per_kwh`. The gateway is a customer-borne pass-through that cancels out of the franchisee's payout. See [[adr-0026-tariff-excludes-gateway-actual-fee]].
