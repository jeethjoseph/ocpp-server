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
Razorpay's real deduction on a captured payment, sourced from the payment webhook or the Razorpay API. Stored on `QRPayment.platform_fee` / `razorpay_commission` / `razorpay_gst`. Used only for ops, reconciliation, and the nightly drift detector — never for customer-facing math.
_Avoid_: real fee, captured fee.

**Budget cap**:
Redis-cached upper bound on energy a **QR Session** can deliver. Equals `(amount_paid - synthetic_fee) / (1 + gst_pct/100) / rate_per_kwh`. Enforced from the MeterValues handler by dispatching `RemoteStopTransaction` when consumption crosses the cap.
_Avoid_: limit, cap.

### Billing artefacts

**GST Invoice**:
A `GSTInvoice` row issued per billable charging session. Supplier is always VoltLync (merchant-of-record); the franchisee operator is captured as a snapshot block on the PDF (Razorpay disclosure requirement). Never issued for zero-energy sessions, internal-role sessions, or wallet top-ups.
_Avoid_: receipt, bill.

## Relationships

- A **Charging Session** is funded by either a **Wallet** (debit at finalize) or a **QR Payment** (prepaid, refund-on-finalize).
- A **QR Payment** carries both an **Actual platform fee** (truth from Razorpay) and a **Synthetic platform fee** (policy, fixed). They are not expected to be equal; variance is absorbed by VoltLync.
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
