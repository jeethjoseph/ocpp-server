# VoltLync Franchisee Management Module - Specification Document

| Field | Value |
|-------|-------|
| **Version** | 1.0 (Draft) |
| **Date** | 2026-03-26 |
| **Status** | Proposed |
| **System** | VoltLync OCPP 1.6 CSMS |
| **Backend** | FastAPI + Tortoise ORM + PostgreSQL + Redis |
| **Frontend** | Next.js 15 + React 19 + TanStack Query |
| **Payments** | Razorpay SDK 2.0.0 + Route (to be integrated) |

---

## 1. Executive Summary

This specification defines a Franchisee Management Module that transitions VoltLync from a single-operator model to a multi-party franchise platform. Franchisees own and operate physical charging stations; VoltLync acts as the platform aggregator -- collecting payments from EV drivers, deducting its commission and applicable taxes, and transferring the remainder to franchisees via Razorpay Route in real-time after each charging session.

**Key design decisions:**
- **Real-time per-transaction settlement** -- franchisee receives payout immediately after each session
- **Razorpay Route linked accounts** -- franchisees onboarded as KYC-verified sub-merchants
- **Configurable TDS** -- default 10% per CA advice, adjustable per franchisee
- **Flat per-franchisee commission** -- single percentage applied to all their stations
- **Near-full franchisee portal** -- everything except firmware updates

The design preserves all existing payment flows (wallet top-up, QR appless charging) and layers settlement logic on top. The franchisee module is purely additive -- not a rewrite.

---

## 2. Glossary

| Term | Definition |
|------|-----------|
| **Franchisee** | Business entity that owns/operates one or more charging stations under VoltLync |
| **Linked Account** | Razorpay Route sub-merchant registered under VoltLync's Razorpay account (`acc_XXXX`) |
| **Transfer** | Movement of funds from VoltLync's Razorpay balance to a franchisee linked account |
| **Settlement** | Razorpay disbursing transferred funds to franchisee's bank account (T+2 working days) |
| **PG Fee** | Razorpay payment gateway fee (~2% cards, ~0.5% UPI) charged on total payment |
| **Transfer Fee** | Razorpay Route fee (~0.25%) on amount transferred to linked account |
| **Platform Commission** | VoltLync's negotiated percentage of net charging revenue |
| **TDS** | Tax Deducted at Source -- configurable rate, default 10% per CA recommendation |
| **GST** | 18% Goods and Services Tax, added on top of the tariff rate (not inclusive) |
| **FOCO** | Franchise Owned, Company Operated |

---

## 3. Data Model Design

### 3.1 New Enums

```python
class FranchiseeStatusEnum(str, enum.Enum):
    DRAFT = "DRAFT"                              # Profile created, KYC not started
    KYC_SUBMITTED = "KYC_SUBMITTED"              # Documents submitted to Razorpay
    KYC_UNDER_REVIEW = "KYC_UNDER_REVIEW"        # Razorpay reviewing
    KYC_NEEDS_CLARIFICATION = "KYC_NEEDS_CLARIFICATION"  # Razorpay needs more info
    ACTIVE = "ACTIVE"                            # KYC approved, can receive transfers
    SUSPENDED = "SUSPENDED"                      # Temporarily blocked (disputes, compliance)
    DEACTIVATED = "DEACTIVATED"                  # Permanently removed

class FranchiseeBusinessTypeEnum(str, enum.Enum):
    INDIVIDUAL = "INDIVIDUAL"
    PROPRIETORSHIP = "PROPRIETORSHIP"
    PARTNERSHIP = "PARTNERSHIP"
    PRIVATE_LIMITED = "PRIVATE_LIMITED"
    LLP = "LLP"

class SettlementStatusEnum(str, enum.Enum):
    PENDING = "PENDING"                          # Calculated, awaiting transfer attempt
    TRANSFER_INITIATED = "TRANSFER_INITIATED"    # Razorpay transfer API called
    TRANSFER_PROCESSED = "TRANSFER_PROCESSED"    # Razorpay webhook confirmed transfer
    SETTLED = "SETTLED"                          # Funds in franchisee bank
    FAILED = "FAILED"                            # Transfer failed
    REVERSED = "REVERSED"                        # Transfer reversed (post-settlement refund)
    ON_HOLD = "ON_HOLD"                          # Manually held (dispute, audit)
    BELOW_THRESHOLD = "BELOW_THRESHOLD"          # Terminal: payout < MINIMUM_TRANSFER_AMOUNT, no transfer attempted

class CommissionChangeReasonEnum(str, enum.Enum):
    INITIAL_SETUP = "INITIAL_SETUP"
    CONTRACT_RENEWAL = "CONTRACT_RENEWAL"
    PERFORMANCE_ADJUSTMENT = "PERFORMANCE_ADJUSTMENT"
    PROMOTION = "PROMOTION"
    ADMIN_OVERRIDE = "ADMIN_OVERRIDE"

class InvoiceStatusEnum(str, enum.Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    CANCELLED = "CANCELLED"
```

### 3.2 Existing Enum Changes

```python
class UserRoleEnum(str, enum.Enum):
    ADMIN = "ADMIN"
    USER = "USER"
    FRANCHISEE = "FRANCHISEE"  # NEW: franchisee portal access
```

### 3.3 New Models

#### Franchisee

```python
class Franchisee(Model):
    id = fields.IntField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    # Identity
    business_name = fields.CharField(max_length=255)
    business_type = fields.CharEnumField(FranchiseeBusinessTypeEnum)
    contact_name = fields.CharField(max_length=255)
    contact_email = fields.CharField(max_length=255, unique=True)
    contact_phone = fields.CharField(max_length=20)
    address = fields.TextField(null=True)

    # Tax/Legal
    pan_number = fields.CharField(max_length=10, unique=True)       # 10-char Indian PAN
    gstin = fields.CharField(max_length=15, unique=True, null=True) # 15-char GSTIN (nullable)
    tan_number = fields.CharField(max_length=10, null=True)         # For TDS certificates

    # Bank Details (reference copy; Razorpay holds canonical)
    bank_account_name = fields.CharField(max_length=255, null=True)
    bank_account_number = fields.CharField(max_length=30, null=True)
    bank_ifsc_code = fields.CharField(max_length=11, null=True)

    # Razorpay Route Integration
    razorpay_account_id = fields.CharField(max_length=50, unique=True, null=True)  # acc_XXXX
    razorpay_account_status = fields.CharField(max_length=50, null=True)
    kyc_submitted_at = fields.DatetimeField(null=True)
    kyc_verified_at = fields.DatetimeField(null=True)

    # Commission
    commission_percent = fields.DecimalField(max_digits=5, decimal_places=2, default=20.00)
    commission_effective_from = fields.DateField(auto_now_add=True)

    # TDS (configurable per franchisee, default 10%)
    tds_rate_percent = fields.DecimalField(max_digits=5, decimal_places=2, default=10.00)
    tds_pan_verified = fields.BooleanField(default=False)

    # Status
    status = fields.CharEnumField(FranchiseeStatusEnum, default=FranchiseeStatusEnum.DRAFT)
    status_reason = fields.TextField(null=True)
    activated_at = fields.DatetimeField(null=True)
    deactivated_at = fields.DatetimeField(null=True)

    # Admin
    onboarded_by = fields.ForeignKeyField("models.User", related_name="onboarded_franchisees", null=True)
    notes = fields.TextField(null=True)

    # User account for portal access
    user = fields.OneToOneField("models.User", related_name="franchisee_profile", null=True)

    # Relationships
    stations: fields.ReverseRelation["ChargingStation"]
    ledger_entries: fields.ReverseRelation["CommissionLedgerEntry"]
    audit_logs: fields.ReverseRelation["CommissionAuditLog"]
    invoices: fields.ReverseRelation["FranchiseeInvoice"]

    class Meta:
        table = "franchisee"
```

#### CommissionLedgerEntry (per-transaction settlement record)

```python
class CommissionLedgerEntry(Model):
    id = fields.IntField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    # Links
    transaction = fields.OneToOneField("models.Transaction", related_name="settlement")
    franchisee = fields.ForeignKeyField("models.Franchisee", related_name="ledger_entries")
    qr_payment = fields.ForeignKeyField("models.QRPayment", related_name="settlement", null=True)
    wallet_transaction = fields.ForeignKeyField("models.WalletTransaction", related_name="settlement", null=True)

    # Gross
    gross_amount = fields.DecimalField(max_digits=10, decimal_places=2)       # What customer paid
    payment_method = fields.CharField(max_length=20)                          # WALLET | QR_UPI
    razorpay_payment_id = fields.CharField(max_length=255, null=True)

    # Deductions
    refund_amount = fields.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    pg_fee_amount = fields.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    net_amount = fields.DecimalField(max_digits=10, decimal_places=2)         # gross - refund - pg_fee

    # GST (added on top of tariff, collected from customer)
    gst_collected = fields.DecimalField(max_digits=10, decimal_places=2)      # 18% of energy_charge
    net_excl_gst = fields.DecimalField(max_digits=10, decimal_places=2)       # net_amount - gst_collected

    # Commission on net_excl_gst; TDS on franchisee earning (net_excl_gst − platform_commission)
    commission_percent = fields.DecimalField(max_digits=5, decimal_places=2)  # Frozen rate
    platform_commission = fields.DecimalField(max_digits=10, decimal_places=2)
    tds_amount = fields.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    transfer_fee = fields.DecimalField(max_digits=10, decimal_places=2, default=0.00)  # Filled post-settlement from webhook; not deducted from payout

    # Franchisee payout
    franchisee_payout = fields.DecimalField(max_digits=10, decimal_places=2)

    # Energy data (denormalized for reporting)
    energy_consumed_kwh = fields.FloatField()
    tariff_rate_per_kwh = fields.DecimalField(max_digits=5, decimal_places=2)

    # Transfer tracking
    settlement_status = fields.CharEnumField(SettlementStatusEnum, default=SettlementStatusEnum.PENDING)
    razorpay_transfer_id = fields.CharField(max_length=255, unique=True, null=True)
    transfer_initiated_at = fields.DatetimeField(null=True)
    transfer_processed_at = fields.DatetimeField(null=True)
    settled_at = fields.DatetimeField(null=True)

    # Idempotency
    idempotency_key = fields.CharField(max_length=255, unique=True)  # "txn_{transaction_id}"

    class Meta:
        table = "commission_ledger_entry"
```

#### CommissionAuditLog

```python
class CommissionAuditLog(Model):
    id = fields.IntField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    franchisee = fields.ForeignKeyField("models.Franchisee", related_name="commission_audit_logs")
    previous_percent = fields.DecimalField(max_digits=5, decimal_places=2, null=True)
    new_percent = fields.DecimalField(max_digits=5, decimal_places=2)
    reason = fields.CharEnumField(CommissionChangeReasonEnum)
    effective_from = fields.DateField()
    changed_by = fields.ForeignKeyField("models.User", related_name="commission_changes")
    notes = fields.TextField(null=True)

    class Meta:
        table = "commission_audit_log"
```

#### FranchiseeInvoice (monthly tax invoice)

```python
class FranchiseeInvoice(Model):
    id = fields.IntField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    franchisee = fields.ForeignKeyField("models.Franchisee", related_name="invoices")
    invoice_number = fields.CharField(max_length=50, unique=True)  # VL/2026-27/F001
    period_start = fields.DateField()
    period_end = fields.DateField()

    # Aggregated amounts
    total_gross_revenue = fields.DecimalField(max_digits=12, decimal_places=2)
    total_refunds = fields.DecimalField(max_digits=12, decimal_places=2)
    total_pg_fees = fields.DecimalField(max_digits=12, decimal_places=2)
    total_net_revenue = fields.DecimalField(max_digits=12, decimal_places=2)
    total_gst_collected = fields.DecimalField(max_digits=12, decimal_places=2)  # GST on energy
    total_net_excl_gst = fields.DecimalField(max_digits=12, decimal_places=2)
    total_commission = fields.DecimalField(max_digits=12, decimal_places=2)
    total_tds = fields.DecimalField(max_digits=12, decimal_places=2)
    total_transfer_fees = fields.DecimalField(max_digits=12, decimal_places=2)
    total_franchisee_payout = fields.DecimalField(max_digits=12, decimal_places=2)

    # Metadata
    transaction_count = fields.IntField()
    total_energy_kwh = fields.FloatField()

    status = fields.CharEnumField(InvoiceStatusEnum, default=InvoiceStatusEnum.DRAFT)
    issued_at = fields.DatetimeField(null=True)
    pdf_url = fields.CharField(max_length=500, null=True)

    class Meta:
        table = "franchisee_invoice"
```

### 3.4 Existing Model Changes

**ChargingStation** -- add nullable FK:
```python
# New field on ChargingStation
franchisee = fields.ForeignKeyField(
    "models.Franchisee", related_name="stations", null=True, on_delete=fields.SET_NULL
)
```

When `franchisee_id IS NULL`, the station is VoltLync-owned. This is backward compatible with all existing data.

### 3.5 Model Relationship Diagram

```
Franchisee (1) ──< ChargingStation (N)
     │                    │
     │                    └──< Charger (N)
     │                             │
     │                             └──< Transaction (N)
     │                                       │
     └──< CommissionLedgerEntry (N) ─────────┘ (1:1 with Transaction)
     │            │
     │            ├── links to QRPayment (optional)
     │            └── links to WalletTransaction (optional)
     │
     ├──< CommissionAuditLog (N)
     │
     ├──< FranchiseeInvoice (N)
     │
     └── User (1:1, for portal login)
```

---

## 4. Prerequisite: GST Billing (System-Wide Change) -- IMPLEMENTED

> **Status: COMPLETED.** GST billing has been implemented in migration `13_20260326133707_add_gst_billing_fields.py`. Fields added: `Tariff.gst_percent`, `Transaction.{energy_charge, gst_amount, total_billed}`, `QRPayment.gst_amount`. WalletService and QRPaymentService updated. Frontend displays updated.

~~The current billing system has **no GST logic**. Before implementing the franchisee module, the billing system must be updated to add 18% GST on top of the tariff rate for **all** charging sessions (VoltLync-owned and franchisee-owned).~~

### 4.1 Current Billing (No GST)

```
Wallet:  billing_amount = energy_kwh * rate_per_kwh
QR:      energy_cost = energy_kwh * rate_per_kwh
         refund = amount_paid - energy_cost - platform_fee
```

### 4.2 Updated Billing (With GST)

```
Wallet:  energy_charge = energy_kwh * rate_per_kwh
         gst = energy_charge * 18%
         billing_amount = energy_charge + gst

QR:      energy_charge = energy_kwh * rate_per_kwh
         gst = energy_charge * 18%
         energy_cost_with_gst = energy_charge + gst
         refund = amount_paid - energy_cost_with_gst - platform_fee
```

### 4.3 Model Changes

**Tariff** -- add GST rate field:
```python
# New field on Tariff model
gst_percent = fields.DecimalField(max_digits=5, decimal_places=2, default=18.00)
```

**Transaction** -- add GST tracking fields:
```python
# New fields on Transaction model
energy_charge = fields.DecimalField(max_digits=10, decimal_places=2, null=True)  # Pre-GST
gst_amount = fields.DecimalField(max_digits=10, decimal_places=2, null=True)     # GST collected
total_billed = fields.DecimalField(max_digits=10, decimal_places=2, null=True)   # energy_charge + gst
```

**QRPayment** -- add GST tracking fields:
```python
# New fields on QRPayment model
# Currently has: amount_paid, energy_cost, platform_fee, refund_amount
# Rename energy_cost -> energy_charge (pre-GST) and add:
gst_amount = fields.DecimalField(max_digits=10, decimal_places=2, null=True)     # 18% of energy_charge
energy_cost_with_gst = fields.DecimalField(max_digits=10, decimal_places=2, null=True)  # energy_charge + gst
```

The existing `energy_cost` field on QRPayment should be treated as the pre-GST energy charge. New fields track the GST component separately so refund calculation becomes:
```
refund = amount_paid - energy_charge - gst_amount - platform_fee
```

### 4.4 Service Changes

**WalletService.calculate_billing_amount()** (`backend/services/wallet_service.py`):
```python
# Current: amount = energy_kwh * rate_per_kwh
# Updated:
energy_charge = (energy_kwh * rate_per_kwh).quantize(Decimal('0.01'), ROUND_HALF_UP)
gst = (energy_charge * gst_percent / 100).quantize(Decimal('0.01'), ROUND_HALF_UP)
billing_amount = energy_charge + gst
# Return all three for transaction record
```

**WalletService.process_transaction_billing()**: Deduct `billing_amount` (energy + GST) from wallet. Store `energy_charge`, `gst_amount`, `total_billed` on Transaction.

**QRPaymentService.process_qr_session_billing()** (`backend/services/qr_payment_service.py`):
```python
# Current: energy_cost = energy_kwh * tariff_rate
#          refund = amount_paid - energy_cost - platform_fee
# Updated:
energy_charge = (energy_kwh * tariff_rate).quantize(Decimal('0.01'), ROUND_HALF_UP)
gst = (energy_charge * gst_percent / 100).quantize(Decimal('0.01'), ROUND_HALF_UP)
energy_cost_with_gst = energy_charge + gst
refund = max(Decimal('0'), amount_paid - energy_cost_with_gst - platform_fee)
```

**QRPaymentService.link_transaction_to_qr_payment()**: Update budget calculation to account for GST:
```python
# Budget must cover energy + GST, not just energy
budget_limit = float(amount_paid - platform_fee)  # unchanged -- GST comes from this budget
```

### 4.5 QR Budget Check Impact

The budget check during MeterValues (`check_budget_and_auto_stop`) currently compares `cost_so_far` against `budget_limit`. With GST:
```python
# Current: cost_so_far = (meter_kwh - start_kwh) * tariff_rate
# Updated: cost_so_far = (meter_kwh - start_kwh) * tariff_rate * 1.18  (include GST)
```
This ensures auto-stop triggers before the customer's budget is exceeded including GST.

### 4.6 Customer-Facing Display

Billing breakdown shown to customers should separate:
- Energy charge: Rs.X
- GST (18%): Rs.Y
- Total: Rs.X + Rs.Y

### 4.7 Migration

- Add `gst_percent` to Tariff (default 18.00)
- Add `energy_charge`, `gst_amount`, `total_billed` to Transaction (nullable for historical data)
- Add `gst_amount`, `energy_cost_with_gst` to QRPayment (nullable for historical data)
- Existing transactions: `energy_charge = billing_amount`, `gst_amount = 0`, `total_billed = billing_amount`
- Existing QR payments: `gst_amount = 0`, `energy_cost_with_gst = energy_cost`

### 4.8 Customer-Facing GST Tax Invoice Issuance -- IN SCOPE FOR THIS MODULE

> **Status: NOT YET IMPLEMENTED.** Section 4 above adds the GST *math* (calculation, storage, display). It does **not** issue GST-compliant tax invoices. Sequential invoice issuance is scoped here because the supplier identity on the customer-facing invoice depends on the franchisee model.

**Distinction from `FranchiseeInvoice` (Section 6):**

| Document | Issued by → to | Frequency | Purpose |
|---|---|---|---|
| **`gst_invoice`** (new, this section) | Franchisee → EV driver | Per charging session | Tax invoice for the supply of charging services. CGST/SGST/IGST split, sequential per CGST Rule 46. The customer's receipt. |
| **`FranchiseeInvoice`** (Section 6.x) | VoltLync → Franchisee | Monthly | Commission/platform-fee invoice from VoltLync to franchisee, aggregating settlement for the period. A separate B2B document. |

These are two **different** GST documents serving two different supplier-customer relationships. Both are needed; neither replaces the other.

#### 4.8.1 Why this work belongs in the franchisee module

1. **The supplier on the customer's invoice is the franchisee.** Under the Razorpay Route model, the franchisee is the merchant of record for the charging supply. The invoice header (legal name, GSTIN, address) comes from the `Franchisee` row, not from VoltLync. You cannot design the invoice schema until you know whose name goes on it.
2. **Sequential counter scope = GSTIN scope.** CGST Rule 46 requires gapless sequential numbering *per supplier per financial year*. Each franchisee is a separate legal entity with its own GSTIN, so each franchisee needs its own counter. The counter table PK must include `franchisee_id`.
3. **Place of supply is derived from `charger → station → franchisee`.** The franchisee module already wires `ChargingStation.franchisee_id`, which is the chain needed to determine intra-state (CGST+SGST) vs inter-state (IGST) tax split.
4. **Credit notes for QR refunds need Route plumbing.** A QR refund creates a GST credit note against the original invoice. The refund itself is processed against the franchisee's linked account, so the credit note flow depends on the Route integration.

#### 4.8.2 New tables required

Detailed schema is tracked separately. High-level summary:

**`gst_invoice`** -- one row per charging session that produced billable energy. Snapshot-based (customer details, supplier details, charger location, tariff rate, HSN code are all frozen at issue time so the document is immutable). Fields:
- Identity: `id`, `franchisee_id`, `series` (`WALLET` | `QR`), `financial_year`, `sequence_number`, `invoice_number` (e.g. `VL/F12/WAL/2026-27/00001`), `invoice_date`, `status` (`ISSUED` | `CANCELLED`)
- Linkage: `transaction_id`, `wallet_transaction_id` or `qr_payment_id`, `user_id` (nullable for anonymous QR)
- Customer snapshot: name, address, state, state_code, phone, email, gstin (nullable), customer_type (`B2C` | `B2B`)
- Supplier snapshot: legal_name, gstin, address, state_code (snapshotted from `Franchisee`)
- Place of supply: state, state_code, `is_inter_state`
- Charger snapshot: charger_id, serial_number, location
- Supply line item: hsn_sac_code, description, energy_consumed_kwh, rate_per_kwh
- Tax breakdown: taxable_value, gst_rate, cgst_rate, cgst_amount, sgst_rate, sgst_amount, igst_rate, igst_amount, total_amount, amount_in_words
- Audit: issued_at, cancelled_at, cancellation_reason, pdf_url

**`gst_invoice_counter`** -- the source of truth for "next number" per (franchisee, series, FY). Locked with `SELECT FOR UPDATE` inside the same DB transaction as the invoice insert. PK: `(franchisee_id, series, financial_year)`. Column: `last_number INT`. **Do not use a PostgreSQL sequence** -- sequences are non-transactional and rolled-back inserts create gaps, which is an audit problem under GST.

**`gst_credit_note`** -- mirrors `gst_invoice` but always references an `original_invoice_id`. Used for QR refunds, billing corrections, and invoice cancellations. Has its own series (`CN_WALLET`, `CN_QR`) and reuses `gst_invoice_counter` for numbering. Links to `razorpay_refund_id` (for QR) or `wallet_transaction_id` (for wallet credit-back).

#### 4.8.3 Modifications to existing tables

- **`Franchisee`** (already in Section 3.3): no schema changes -- existing `gstin`, `business_name`, `address` fields are sufficient. State/state_code may need to be added for place-of-supply derivation if not parseable from `address`.
- **`charging_station`**: add `state`, `state_code`, `pincode` columns. Backfill required for existing stations before invoicing goes live.
- **`app_user`**: add nullable `gstin`, `billing_name`, `billing_address`, `billing_state`, `billing_state_code` for B2B customers who want input tax credit.
- **`tariff`**: add `hsn_sac_code VARCHAR(10)` (default to a CA-confirmed value for EV charging services).

#### 4.8.4 Open decisions

These must be answered before implementation:

1. **QR invoice timing.** Strict GST: invoice the full prepaid amount at `payment.captured`, then credit-note the unused at `StopTransaction`. Pragmatic: invoice only the actual energy used at `StopTransaction`. **Recommendation: pragmatic, pending CA confirmation.**
2. **Anonymous QR ≥ Rs.200.** Rule 46 requires customer name + address above Rs.200. Options: (a) hard-cap anonymous QR at Rs.199, (b) force phone capture before plug-in, (c) accept non-compliance for sub-Rs.200 sessions only and rely on the consolidated-invoice provision. **Recommendation: (a) initially, revisit after observing usage patterns.**
3. **HSN/SAC code for EV charging.** No settled industry standard (9966 vs 998714 vs 9987 are all in use). Confirm with CA and store on `tariff`.
4. **Cancellation policy.** Who can cancel an issued invoice? What audit trail? Frontend or admin-only?

#### 4.8.5 Implementation phase placement

This work belongs in **Phase 3** (post-Razorpay-Route integration, post-`Franchisee` model creation). It cannot ship before franchisee onboarding because the supplier identity is unresolved without it. It must ship before the first franchisee goes live with real charging sessions, because every billable session needs a tax invoice from day one.

---

## 5. Razorpay Route Onboarding

### 5.1 Self-Onboarding Flow

Franchisees onboard themselves. Admin only creates the initial profile with minimal info and assigns stations.

```
Admin creates franchisee with minimal info
(business_name, contact_email, contact_phone, commission_percent)
        │
        ▼
System creates User account (role: FRANCHISEE)
System sends invite email with login link to franchisee
(status: DRAFT)
        │
        ▼
Franchisee logs into portal, sees "Complete KYC" prompt
        │
        ▼
Franchisee fills KYC form in portal:
    - Business type, PAN, GSTIN, bank details
    - Upload documents (Aadhaar, COI, etc.)
        │
        ▼
Franchisee clicks "Submit KYC"
→ Backend validates fields
→ Backend calls Razorpay POST /v2/accounts
(status: KYC_SUBMITTED)
        │
        ▼
Razorpay async KYC review
        │
        ▼
Razorpay webhook result:
    ├── account.activated → status = ACTIVE
    │     Store razorpay_account_id, kyc_verified_at
    │     Franchisee sees "KYC Approved" in portal
    │
    ├── account.needs_clarification → status = KYC_NEEDS_CLARIFICATION
    │     Franchisee sees clarification request, re-submits from portal
    │
    ├── account.under_review → status = KYC_UNDER_REVIEW
    │     Franchisee sees "Under Review" status
    │
    └── account.suspended / rejected → status = SUSPENDED / DRAFT
          Franchisee + admin notified with rejection reason
        │
        ▼
Admin assigns ChargingStations to franchisee (can be done in parallel)
(station.franchisee_id = franchisee.id)
        │
        ▼
Franchisee starts receiving real-time transfers for sessions
```

### 5.2 KYC Requirements by Business Type

| Document | Individual | Proprietorship | Pvt Ltd / LLP |
|----------|-----------|---------------|---------------|
| PAN | Personal PAN | Personal PAN | Company PAN |
| Address proof | Aadhaar / Passport | Shop & Establishment cert | Certificate of Incorporation / LLP Agreement |
| Bank details | Personal savings a/c | Current account | Company current account |
| GST certificate | Optional | Recommended | Required |
| Board resolution | N/A | N/A | Required |
| Authorized signatory | N/A | N/A | Required (director PAN + Aadhaar) |

### 5.3 Razorpay Account Creation Payload

```python
{
    "email": franchisee.contact_email,
    "phone": franchisee.contact_phone,
    "type": "route",
    "legal_business_name": franchisee.business_name,
    "business_type": map_to_razorpay_type(franchisee.business_type),
    "legal_info": {
        "pan": franchisee.pan_number,
        "gst": franchisee.gstin  # if available
    },
    "bank_account": {
        "ifsc_code": franchisee.bank_ifsc_code,
        "beneficiary_name": franchisee.bank_account_name,
        "account_number": franchisee.bank_account_number
    },
    "profile": {
        "category": "electricals_and_electronics",
        "subcategory": "electric_vehicle_charging",
        "addresses": {
            "registered": {
                "street1": franchisee.address,
                "city": "...",
                "state": "...",
                "postal_code": "...",
                "country": "IN"
            }
        }
    },
    "notes": {
        "voltlync_franchisee_id": str(franchisee.id)
    }
}
```

### 5.4 KYC Webhook Events

New events to handle in the existing `/webhooks/razorpay` endpoint:

| Event | Action |
|-------|--------|
| `account.under_review` | Update status to `KYC_UNDER_REVIEW` |
| `account.activated` | Update status to `ACTIVE`, store `razorpay_account_id`, set `kyc_verified_at` |
| `account.needs_clarification` | Update status to `KYC_NEEDS_CLARIFICATION`, store reason |
| `account.suspended` | Update status to `SUSPENDED` |
| `account.rejected` | Update status to `DRAFT`, store rejection reason, notify admin |

---

## 6. Settlement Engine

### 6.1 Settlement Formula

**GST Model:** The tariff rate (e.g., Rs.14/kWh) is **pre-GST**. 18% GST is added on top when billing the customer. The customer's total bill includes both the energy charge and GST as separate line items.

For each completed charging transaction at a franchisee-owned station:

```
INPUTS:
    energy_consumed_kwh = kWh consumed during session
    tariff_rate         = Per-kWh rate (pre-GST)
    gst_rate            = 18% (on energy charge)
    refund_amount       = Refund issued (QR unused balance, or 0 for wallet)
    pg_fee              = Razorpay PG fee (commission + GST from webhook; ~2%)
    commission_pct      = Franchisee's commission rate (frozen at transaction time)
    tds_pct             = Configurable per franchisee (default 10%)

STEP 1: Customer billing
    energy_charge       = energy_consumed_kwh * tariff_rate
    gst_on_energy       = energy_charge * gst_rate / 100
    gross_amount        = energy_charge + gst_on_energy
    (For QR: gross_amount = amount_paid by customer; refund is the overpayment)

STEP 2: Net after PG fees and refunds
    net_amount          = gross_amount - refund_amount - pg_fee

STEP 3: Separate GST component from net
    gst_collected       = gst_on_energy (or proportional if partial refund)
    net_excl_gst        = net_amount - gst_collected
    (GST collected is remitted to government by the service provider)

STEP 4: Platform commission on pre-GST net
    platform_commission = net_excl_gst * commission_pct / 100

STEP 5: TDS on franchisee earning (post-commission)
    franchisee_earning  = net_excl_gst - platform_commission
    tds_amount          = franchisee_earning * tds_pct / 100

    (TDS is withheld from the payment to the franchisee, not from a
    pre-commission base. Withholding on net_excl_gst would over-deduct
    by `platform_commission * tds_pct / 100` on every settlement.)

STEP 6: Franchisee payout
    franchisee_payout   = franchisee_earning - tds_amount

DISTRIBUTION:
    Government (GST):    gst_collected
    Government (TDS):    tds_amount (VoltLync deposits, franchisee claims credit)
    Razorpay (PG fee):   pg_fee
    VoltLync retains:    platform_commission
    Franchisee receives: franchisee_payout
    Customer refunded:   refund_amount

TRANSFER GATING:
    If franchisee_payout < MINIMUM_TRANSFER_AMOUNT (default ₹1.00):
        settlement_status = BELOW_THRESHOLD (terminal, no transfer attempted)
    Else if franchisee is ACTIVE with a razorpay_account_id:
        Initiate Razorpay Route transfer; status = TRANSFER_INITIATED

    transfer_fee is recorded post-settlement from the transfer.processed
    webhook for reconciliation only — NOT deducted from franchisee_payout.
```

All amounts rounded to 2 decimal places with `ROUND_HALF_UP`.

**Note on GST liability:** The franchisee is the service provider (charger owner). GST collected on energy is the franchisee's GST liability to remit. However, since VoltLync collects on behalf, the GST component should be passed through to the franchisee as part of their payout (they remit it). Alternatively, VoltLync can remit GST directly if structured as the service provider. **This needs CA confirmation.** The formula above assumes VoltLync holds the GST component and remits it -- adjust if CA advises otherwise.

### 6.2 Worked Example: QR Payment Session

**Scenario:** Customer pays Rs.500 via UPI QR, consumes 25 kWh at Rs.14/kWh (pre-GST tariff). Franchisee commission: 20%. TDS: 10%. Razorpay PG fee = Rs.10 (~2%, same fee used in Stage 1 refund calc and Stage 2 settlement).

```
Step 1: Energy billing (GST added on top)
    energy_charge       = 25 kWh * Rs.14/kWh = Rs.350.00
    gst_on_energy (18%) = Rs.350.00 * 18% = Rs.63.00
    total_energy_bill   = Rs.350.00 + Rs.63.00 = Rs.413.00

Step 2: QR refund calc (existing flow, before settlement)
    customer_paid       = Rs.500.00
    pg_fee              = Rs.10.00  (from Razorpay webhook)
    refund_amount       = Rs.500.00 - Rs.413.00 - Rs.10.00 = Rs.77.00

Step 3: Settlement -- net after PG fees and refunds
    gross_amount        = Rs.500.00
    net_amount          = Rs.500.00 - Rs.77.00 - Rs.10.00 = Rs.413.00

Step 4: Separate GST from net
    gst_collected       = Rs.63.00
    net_excl_gst        = Rs.413.00 - Rs.63.00 = Rs.350.00

Step 5: Platform commission
    commission (20%)    = Rs.350.00 * 20% = Rs.70.00

Step 6: TDS on franchisee earning (post-commission)
    franchisee_earning  = Rs.350.00 - Rs.70.00 = Rs.280.00
    tds (10%)           = Rs.280.00 * 10% = Rs.28.00

Step 7: Franchisee payout
    franchisee_payout   = Rs.280.00 - Rs.28.00 = Rs.252.00

    (transfer_fee is recorded later from Razorpay's transfer.processed
    webhook; it is NOT deducted from the payout.)

SUMMARY:
    Customer paid:           Rs.500.00
    Customer refunded:       Rs.77.00
    Razorpay PG fee:         Rs.10.00
    GST collected (govt):    Rs.63.00
    VoltLync commission:     Rs.70.00
    TDS deducted (govt):     Rs.28.00
    Franchisee receives:     Rs.252.00
    ──────────────────────────────────
    Total:                   Rs.500.00 ✓
```

### 6.3 Worked Example: Wallet Session

**Scenario:** User charges 10 kWh at Rs.12/kWh (pre-GST). Same franchisee (20% commission, 10% TDS).

```
Step 1: Energy billing (GST added on top)
    energy_charge       = 10 kWh * Rs.12/kWh = Rs.120.00
    gst_on_energy (18%) = Rs.120.00 * 18% = Rs.21.60
    total_deducted      = Rs.120.00 + Rs.21.60 = Rs.141.60 (from wallet)

Step 2: Settlement
    gross_amount        = Rs.141.60
    refund_amount       = Rs.0.00 (wallet = exact billing)
    pg_fee              = Rs.0.00 (PG fee absorbed by VoltLync during wallet top-up)
    net_amount          = Rs.141.60

Step 3: Separate GST
    gst_collected       = Rs.21.60
    net_excl_gst        = Rs.141.60 - Rs.21.60 = Rs.120.00

Step 4: Platform commission
    commission (20%)    = Rs.120.00 * 20% = Rs.24.00

Step 5: TDS on franchisee earning (post-commission)
    franchisee_earning  = Rs.120.00 - Rs.24.00 = Rs.96.00
    tds (10%)           = Rs.96.00 * 10% = Rs.9.60

Step 6: Franchisee payout
    franchisee_payout   = Rs.96.00 - Rs.9.60 = Rs.86.40

SUMMARY:
    Wallet deducted:         Rs.141.60
    GST collected (govt):    Rs.21.60
    VoltLync commission:     Rs.24.00
    TDS deducted (govt):     Rs.9.60
    Franchisee receives:     Rs.86.40
    ──────────────────────────────────
    Total:                   Rs.141.60 ✓
```

**Note on wallet PG fees:** The Razorpay PG fee for wallet sessions was already incurred during the wallet top-up, not during the charging session. For wallet-based billing, `pg_fee_amount = 0` in the ledger entry. The PG fee is VoltLync's cost of processing the top-up, absorbed by VoltLync.

**Note on wallet billing change:** Currently the wallet deducts only `energy_charge` (pre-GST). With this module, wallet billing must deduct `energy_charge + GST` from the wallet. This is a change to the existing `WalletService.process_transaction_billing()` flow.

### 6.4 Integration Points

Settlement hooks into the **two existing billing paths** without modifying them. New code runs after existing billing completes:

**Path A: Wallet sessions** (in `on_stop_transaction` in `main.py`)
```python
# After WalletService.process_transaction_billing(transaction_id) succeeds
await FranchiseeSettlementService.process_settlement(transaction_id)
```

**Path B: QR sessions** (in `QRPaymentService.process_qr_session_billing`)
```python
# After QR billing and refund completes
await FranchiseeSettlementService.process_settlement(transaction_id)
```

The settlement service first checks if the charger's station belongs to a franchisee. If `franchisee_id IS NULL`, it returns immediately -- no settlement needed for VoltLync-owned stations.

### 6.5 Real-Time Transfer Flow

Since settlement is per-transaction (real-time), the flow after each session:

```
StopTransaction received
        │
        ▼
Existing billing completes (wallet debit or QR refund)
        │
        ▼
FranchiseeSettlementService.process_settlement(transaction_id)
    ├── Resolve franchisee (charger.station.franchisee_id)
    ├── If no franchisee → return (VoltLync-owned)
    ├── If franchisee status != ACTIVE → create ledger entry as PENDING, skip transfer
    ├── Calculate all line items (formula above)
    ├── Create CommissionLedgerEntry (idempotency_key = "txn_{transaction_id}")
    ├── Call Razorpay Route transfer API:
    │     POST /v1/transfers
    │     {
    │       "account": franchisee.razorpay_account_id,
    │       "amount": int(franchisee_payout * 100),  // paise
    │       "currency": "INR",
    │       "notes": { "transaction_id": ..., "franchisee_id": ..., "idempotency_key": ... }
    │     }
    │     Header: X-Razorpay-Idempotency-Key: "txn_{transaction_id}"
    ├── Update ledger entry: status = TRANSFER_INITIATED, razorpay_transfer_id = ...
    └── Return
        │
        ▼
Razorpay processes transfer (async)
        │
        ▼
Webhook: transfer.processed → Update ledger: status = TRANSFER_PROCESSED
Webhook: settlement.processed → Update ledger: status = SETTLED (funds in bank)
Webhook: transfer.failed → Update ledger: status = FAILED, alert admin
```

### 6.6 Razorpay Service Extensions

New methods on `RazorpayService` (`backend/services/razorpay_service.py`):

```python
# Linked Account Management
def create_linked_account(self, payload: Dict) -> Dict:
    """POST /v2/accounts -- Create franchisee linked account"""

def fetch_linked_account(self, account_id: str) -> Dict:
    """GET /v2/accounts/{account_id} -- Get account status"""

# Transfers
def create_transfer(self, account_id: str, amount_paise: int,
                    notes: Dict, idempotency_key: str) -> Dict:
    """POST /v1/transfers -- Transfer funds to linked account"""

def fetch_transfer(self, transfer_id: str) -> Dict:
    """GET /v1/transfers/{transfer_id} -- Check transfer status"""

def reverse_transfer(self, transfer_id: str, amount_paise: Optional[int] = None) -> Dict:
    """POST /v1/transfers/{transfer_id}/reversals -- Reverse a transfer"""
```

### 6.7 Webhook Handling

New events in the existing `/webhooks/razorpay` handler:

| Event | Handler | Action |
|-------|---------|--------|
| `transfer.processed` | `handle_transfer_processed()` | Update CommissionLedgerEntry status to `TRANSFER_PROCESSED` |
| `transfer.failed` | `handle_transfer_failed()` | Mark as `FAILED`, store error, alert admin |
| `transfer.reversed` | `handle_transfer_reversed()` | Mark as `REVERSED`, update ledger |
| `settlement.processed` | `handle_settlement_processed()` | Update to `SETTLED` |
| `account.*` | `handle_account_webhook()` | Route to FranchiseeOnboardingService |

### 6.8 Idempotency

| Operation | Idempotency Key | Storage |
|-----------|----------------|---------|
| Ledger entry creation | `txn_{transaction_id}` | `commission_ledger_entry.idempotency_key` (UNIQUE) |
| Razorpay transfer | `txn_{transaction_id}` | `X-Razorpay-Idempotency-Key` header |
| Webhook processing | Razorpay `event_id` | `webhook_event.event_id` (UNIQUE, existing) |

### 6.9 Retry Logic for Failed Transfers

Add to the existing `BillingRetryService` (`backend/services/billing_retry_service.py`):

```
_process_failed_franchisee_transfers():
    - Find CommissionLedgerEntry with status = FAILED
    - Retry Razorpay transfer API call
    - After 3 consecutive failures: pause transfers for franchisee, alert admin
    - Runs alongside existing retry jobs (every 30 minutes)
```

---

## 7. Commission & Tax Management

### 7.1 Commission Structure

- **Flat per-franchisee**: Single `commission_percent` on the `Franchisee` model
- **Default**: 20% (configurable via env var `DEFAULT_COMMISSION_PERCENT`)
- **Rate freezing**: When a `CommissionLedgerEntry` is created, the current `commission_percent` is copied into the entry. Retroactive changes do not affect already-calculated settlements.

### 7.2 Commission Change Workflow

1. Admin updates `Franchisee.commission_percent` via API
2. System creates `CommissionAuditLog` entry with previous/new values, reason, effective date
3. All future ledger entries use the new rate
4. Existing entries (any status) are NOT recalculated

### 7.3 TDS Configuration

- **Default rate**: 10% (per CA recommendation)
- **Stored per franchisee**: `Franchisee.tds_rate_percent`
- **Admin can override**: Per-franchisee TDS rate via API (e.g., 0% for exempt entities, 5%, 10%)
- **PAN verification flag**: `tds_pan_verified` -- admin marks after verifying PAN

### 7.4 GST

- **Rate**: 18% added on top of tariff rate (not inclusive)
- **Customer bill**: energy_charge + 18% GST = total billed amount
- **GST collected**: Tracked per transaction in `CommissionLedgerEntry.gst_collected`
- **Commission**: Calculated on `net_excl_gst` (pre-GST net), NOT on the GST-inclusive amount
- **TDS**: Calculated on franchisee earning (`net_excl_gst − platform_commission`), so the withholding base is the payment actually flowing to the franchisee
- **GST liability**: Needs CA confirmation -- either franchisee remits (pass through in payout) or VoltLync remits as aggregator
- **VoltLync claims ITC**: On Razorpay PG fees (18% GST on Razorpay fees)
- **Monthly invoice**: Includes GST breakdown for both parties' filing

### 7.5 Monthly Invoice Generation

At the end of each month (or on-demand by admin):
1. Aggregate all `TRANSFER_PROCESSED` / `SETTLED` ledger entries for the franchisee in the period
2. Create `FranchiseeInvoice` with totals
3. Generate PDF invoice (commission + GST breakdown)
4. Invoice used for:
   - VoltLync's GST filing (output tax on commission)
   - Franchisee's GST filing (input tax credit on commission paid)
   - TDS certificate reference

---

## 8. Franchisee Portal

### 8.1 Access Model

- Franchisee is linked to a `User` record with `role = FRANCHISEE`
- The `User.franchisee_profile` (OneToOne) determines which franchisee they belong to
- All queries are scoped: `WHERE station.franchisee_id = current_user.franchisee_profile.id`

### 8.2 Permissions Matrix

| Capability | Admin | Franchisee | User |
|-----------|-------|-----------|------|
| **Dashboard** | Global | Own stations only | Personal |
| **Stations** | All CRUD | View own stations | Public view |
| **Chargers** | All CRUD | View/manage own chargers | -- |
| **Remote Start/Stop** | All chargers | Own chargers only | Own sessions |
| **Reset Charger** | All | Own chargers (Soft only) | -- |
| **Change Availability** | All | Own chargers | -- |
| **Transactions** | All | Own station transactions | Own |
| **Meter Values** | All | Own station transactions | Own |
| **OCPP Logs** | All | Own charger logs | -- |
| **QR Codes** | All CRUD | View/create for own chargers | -- |
| **Settlements** | All + manage | View own settlements | -- |
| **Invoices** | All + generate | View/download own | -- |
| **Users** | All CRUD | -- | -- |
| **Firmware Updates** | Full access | **No access** | -- |
| **Franchisee Mgmt** | Full CRUD | View own profile | -- |
| **Signal Quality** | All | Own chargers | -- |
| **Charger Errors** | All | Own chargers | -- |

### 8.3 Frontend Routes

New routes under `/franchisee/`:

```
/franchisee/dashboard          - Earnings summary, station status, recent sessions
/franchisee/stations           - List of assigned stations with charger status
/franchisee/stations/[id]      - Station detail with charger management
/franchisee/chargers/[id]      - Charger detail (remote commands, logs, errors, signal)
/franchisee/transactions       - All transactions at own stations (paginated, filterable)
/franchisee/transactions/[id]  - Transaction detail with meter values
/franchisee/qr-codes           - QR codes for own chargers
/franchisee/settlements        - Settlement history with per-transaction breakdown
/franchisee/invoices           - Monthly invoices with PDF download
/franchisee/profile            - View own franchisee profile (read-only, changes via admin)
/franchisee/kyc                - KYC onboarding form (fill details, upload docs, submit)
```

### 8.4 Authentication & Middleware

- Extend Clerk middleware to protect `/franchisee(.*)` routes
- Backend: new `require_franchisee()` dependency that:
  1. Validates JWT (existing `ClerkJWTBearer`)
  2. Checks `user.role == FRANCHISEE`
  3. Resolves `user.franchisee_profile` and injects into request state
- All franchisee router queries filter by `franchisee_id` from request state

### 8.5 Backend Router

New router: `/api/franchisee/` with endpoints mirroring admin capabilities but scoped:

```
GET  /api/franchisee/dashboard        - Earnings summary, station count, active sessions
GET  /api/franchisee/stations         - Own stations (paginated)
GET  /api/franchisee/stations/{id}    - Station detail (403 if not owned)
GET  /api/franchisee/chargers/{id}    - Charger detail (403 if not owned)
POST /api/franchisee/chargers/{id}/remote-start   - Start charging
POST /api/franchisee/chargers/{id}/remote-stop    - Stop charging
POST /api/franchisee/chargers/{id}/reset          - Soft reset only
POST /api/franchisee/chargers/{id}/availability   - Change availability
GET  /api/franchisee/transactions     - Transactions at own stations
GET  /api/franchisee/transactions/{id} - Transaction detail with meter values
GET  /api/franchisee/qr-codes         - QR codes for own chargers
POST /api/franchisee/qr-codes         - Create QR code for own charger
GET  /api/franchisee/settlements      - Own settlement history
GET  /api/franchisee/invoices         - Own invoices
GET  /api/franchisee/invoices/{id}/pdf - Download invoice PDF
GET  /api/franchisee/profile          - Own franchisee profile
GET  /api/franchisee/kyc              - KYC status + clarification requests
PUT  /api/franchisee/kyc              - Submit/update KYC details (PAN, GSTIN, bank, biz type)
POST /api/franchisee/kyc/submit       - Submit KYC to Razorpay
POST /api/franchisee/kyc/resubmit     - Resubmit after clarification
GET  /api/franchisee/chargers/{id}/logs    - OCPP logs for own charger
GET  /api/franchisee/chargers/{id}/errors  - Error history for own charger
GET  /api/franchisee/chargers/{id}/signal  - Signal quality for own charger
```

---

## 9. Admin APIs for Franchisee Management

### 9.1 Franchisee CRUD (Admin creates minimal profile, franchisee self-onboards KYC)

```
POST   /api/admin/franchisees
    Body: { business_name, contact_name, contact_email, contact_phone,
            commission_percent, tds_rate_percent, notes }
    Creates franchisee (status: DRAFT) + User account (role: FRANCHISEE)
    Sends invite email with login link to franchisee

GET    /api/admin/franchisees
    Query: ?page=1&limit=10&status=ACTIVE&search=business_name
    Returns paginated list with station count, total revenue

GET    /api/admin/franchisees/{id}
    Returns full detail: profile, KYC status, stations, commission, settlement summary

PUT    /api/admin/franchisees/{id}
    Update admin-managed fields (commission, TDS rate, notes, station assignments)

DELETE /api/admin/franchisees/{id}
    Soft-delete: status = DEACTIVATED, process final settlements, unassign stations
```

### 9.2 Onboarding APIs (admin can view status, franchisee self-submits)

```
GET    /api/admin/franchisees/{id}/kyc-status
    Fetches latest from Razorpay API + local status

POST   /api/admin/franchisees/{id}/resend-invite
    Resend invite email to franchisee
```

**Franchisee self-service KYC endpoints** (see Section 7 portal):
```
GET    /api/franchisee/kyc                - Get current KYC status + any clarification requests
PUT    /api/franchisee/kyc                - Submit/update KYC details (PAN, GSTIN, bank, business type)
POST   /api/franchisee/kyc/submit         - Submit KYC to Razorpay (triggers POST /v2/accounts)
POST   /api/franchisee/kyc/resubmit       - Resubmit after clarification request
```

### 9.3 Station Assignment

```
POST   /api/admin/franchisees/{id}/stations
    Body: { station_ids: [1, 2, 3] }
    Sets franchisee_id on specified stations

DELETE /api/admin/franchisees/{id}/stations/{station_id}
    Sets station.franchisee_id = NULL (reverts to VoltLync-owned)
```

### 9.4 Commission Management

```
PUT    /api/admin/franchisees/{id}/commission
    Body: { new_percent: 18.5, reason: "CONTRACT_RENEWAL", effective_from: "2026-04-01", notes: "..." }
    Updates commission + creates CommissionAuditLog entry

GET    /api/admin/franchisees/{id}/commission-history
    Returns audit log of commission changes
```

### 9.5 Settlement Management

```
GET    /api/admin/settlements
    Query: ?franchisee_id=5&status=PENDING&start_date=...&end_date=...
    Returns paginated ledger entries with totals

GET    /api/admin/settlements/{entry_id}
    Full detail: linked transaction, payment, transfer info

POST   /api/admin/settlements/{entry_id}/hold
    Put entry on hold (dispute investigation)

POST   /api/admin/settlements/{entry_id}/release
    Release held entry, triggers transfer

POST   /api/admin/settlements/retry-failed
    Body: { franchisee_id: 5 } or { all: true }
    Manually retry failed transfers
```

### 9.6 Invoice APIs

```
POST   /api/admin/franchisees/{id}/invoices/generate
    Body: { period_start: "2026-03-01", period_end: "2026-03-31" }
    Aggregates ledger entries, creates invoice

GET    /api/admin/franchisees/{id}/invoices
    Paginated invoice list

GET    /api/admin/invoices/{invoice_id}/pdf
    Download invoice PDF
```

### 9.7 Reporting APIs

```
GET    /api/admin/franchisees/{id}/revenue-summary
    Query: ?period=monthly&start_date=...&end_date=...
    Returns: { total_gross, total_refunds, total_pg_fees, total_net,
               total_gst_collected, total_net_excl_gst,
               total_commission, total_tds, total_payout,
               transaction_count, energy_kwh, per_station_breakdown }

GET    /api/admin/reports/gst-summary
    Query: ?month=2026-03
    Per-franchisee GST summary for filing

GET    /api/admin/reports/tds-summary
    Query: ?quarter=Q4-2025-26
    Per-franchisee TDS summary for Form 26Q filing
```

---

## 10. New Service Layer

### 10.1 FranchiseeSettlementService

**Location:** `backend/services/franchisee_settlement_service.py`

```python
class FranchiseeSettlementService:

    @staticmethod
    async def process_settlement(transaction_id: int) -> Optional[CommissionLedgerEntry]:
        """
        Called after billing completes (wallet or QR).
        Creates CommissionLedgerEntry + initiates Razorpay transfer.
        Returns None for VoltLync-owned stations.
        """

    @staticmethod
    async def resolve_franchisee_for_charger(charger_id: int) -> Optional[Franchisee]:
        """Resolve: charger.station.franchisee_id -> Franchisee or None"""

    @staticmethod
    async def calculate_settlement(
        gross_amount: Decimal,
        refund_amount: Decimal,
        pg_fee_amount: Decimal,
        franchisee: Franchisee,
    ) -> Dict:
        """Pure calculation, no side effects. Returns all line items."""

    @staticmethod
    async def initiate_transfer(entry: CommissionLedgerEntry) -> bool:
        """Call Razorpay Route transfer API. Returns True on success."""

    @staticmethod
    async def handle_transfer_webhook(event_type: str, transfer_data: dict):
        """Process transfer.processed, transfer.failed, etc."""

    @staticmethod
    async def retry_failed_transfers(franchisee_id: Optional[int] = None):
        """Retry FAILED entries. Called by billing retry service."""
```

### 10.2 FranchiseeOnboardingService

**Location:** `backend/services/franchisee_onboarding_service.py`

```python
class FranchiseeOnboardingService:

    @staticmethod
    async def create_linked_account(franchisee_id: int) -> Dict:
        """Build payload from Franchisee record, call POST /v2/accounts"""

    @staticmethod
    async def handle_account_webhook(event_type: str, account_data: dict):
        """Process account lifecycle webhooks, update franchisee status"""

    @staticmethod
    async def refresh_kyc_status(franchisee_id: int) -> Dict:
        """Poll Razorpay for latest KYC status"""
```

### 10.3 FranchiseeInvoiceService

**Location:** `backend/services/franchisee_invoice_service.py`

```python
class FranchiseeInvoiceService:

    @staticmethod
    async def generate_invoice(franchisee_id: int, period_start: date, period_end: date) -> FranchiseeInvoice:
        """Aggregate ledger entries, create invoice record, generate PDF"""

    @staticmethod
    async def generate_invoice_pdf(invoice_id: int) -> str:
        """Generate PDF, store to filesystem, return URL"""
```

---

## 11. Edge Cases

### 11.1 Refund After Transfer

If a refund is issued after the franchisee transfer has already been processed:

1. Create Razorpay transfer reversal: `POST /v1/transfers/{id}/reversals`
2. Update `CommissionLedgerEntry.settlement_status = REVERSED`
3. Create a new negative adjustment ledger entry for reconciliation
4. If reversal fails (funds already settled to bank), VoltLync issues a debit note to franchisee

### 11.2 Franchisee KYC Rejection

- Status set to `DRAFT` with rejection reason
- Stations assigned to this franchisee continue operating
- Ledger entries created with status `PENDING` (transfer skipped)
- Once KYC is approved (status -> `ACTIVE`), pending entries are transferred
- Admin notified to re-submit corrected KYC

### 11.3 Franchisee Deactivation

1. Set `status = DEACTIVATED`, `deactivated_at = now()`
2. Process all remaining `PENDING` ledger entries as final transfers
3. Set `franchisee_id = NULL` on all assigned stations (revert to VoltLync-owned)
4. Generate final invoice for the period
5. Deactivate franchisee's user account
6. Historical data preserved for audit

### 11.4 Zero-Energy Sessions

If `energy_consumed_kwh = 0`, no `CommissionLedgerEntry` is created. Aligns with existing behavior where wallet billing is skipped and QR issues full refund for zero-energy sessions.

### 11.5 Partial Refund (QR Sessions)

QR overpayment refund is already handled by `QRPaymentService`. Settlement uses `energy_cost` (not `amount_paid`) as basis:

```
gross_amount = qr_payment.amount_paid     (e.g. Rs.500)
refund_amount = qr_payment.refund_amount  (e.g. Rs.140)
net_for_settlement = gross - refund - pg_fee
```

### 11.6 Razorpay API Failures

- Transfer calls are idempotent (`X-Razorpay-Idempotency-Key`)
- Failed transfers stay in `PENDING` / `FAILED` status
- Retry service picks them up every 30 minutes
- After 3 consecutive failures for a franchisee: pause transfers, alert admin
- Ledger entry is always created (financial record preserved regardless of transfer outcome)

### 11.7 Dispute / Hold

1. Admin places specific `CommissionLedgerEntry` on `ON_HOLD`
2. Entry excluded from transfers (if still PENDING) or flagged (if already transferred)
3. Admin investigates, then:
   - Releases hold -> entry goes back to `PENDING` -> transferred in next cycle
   - Reverses -> transfer reversal initiated
4. All hold/release actions logged in existing `AuditEvent` table

### 11.8 Concurrent StopTransaction

Idempotency key `txn_{transaction_id}` with UNIQUE constraint prevents duplicate ledger entries even if `process_settlement()` is called multiple times for the same transaction.

### 11.9 Minimum Transfer Amount

Razorpay minimum transfer is Rs.1. If `franchisee_payout < Rs.1.00`:
- Ledger entry created with status `PENDING`
- Transfer skipped
- Amount carried forward and included in next transfer (or invoice adjustment)

---

## 12. Configuration

### 12.1 New Environment Variables

```env
# Franchisee / Razorpay Route
RAZORPAY_ROUTE_ENABLED=true

# Default platform commission for new franchisees (%)
DEFAULT_COMMISSION_PERCENT=20.0

# GST rate on platform commission (%)
GST_RATE_PERCENT=18.0

# Default TDS rate for new franchisees (%)
DEFAULT_TDS_RATE_PERCENT=10.0

# Razorpay Route transfer fee for display/calculation (%)
RAZORPAY_TRANSFER_FEE_PERCENT=0.25

# Minimum Razorpay transfer amount (INR)
MINIMUM_TRANSFER_AMOUNT=1.00

# Max consecutive transfer failures before pausing
MAX_TRANSFER_RETRIES=3
```

---

## 13. Database Migration

### 13.1 Migration Plan

**Migration 13:** `add_franchisee_module`

1. Create `franchisee` table
2. Create `commission_ledger_entry` table
3. Create `commission_audit_log` table
4. Create `franchisee_invoice` table
5. `ALTER TABLE charging_station ADD COLUMN franchisee_id INT NULL REFERENCES franchisee(id) ON DELETE SET NULL`
6. `CREATE INDEX idx_station_franchisee ON charging_station(franchisee_id)`

All new columns on existing tables are nullable -- purely additive migration, zero downtime.

### 13.2 Backward Compatibility

- `charging_station.franchisee_id = NULL` means VoltLync-owned (all existing stations)
- Settlement logic is a no-op for NULL franchisee
- No changes to existing payment flows
- No changes to existing API responses (new fields are additive)

---

## 14. Security

- **PAN/GSTIN**: Sensitive but not secret (appear on invoices). Stored in DB, access restricted to admin + own franchisee
- **Bank details**: Reference copy only. Razorpay holds canonical. Consider encryption at rest
- **Franchisee role isolation**: All queries filter by `franchisee_id` from JWT. Cannot access other franchisees' data
- **Firmware lockout**: Franchisee role explicitly excluded from firmware endpoints
- **Transfer authorization**: Only settlement service can initiate transfers. Admin can hold/release
- **Webhook verification**: Same HMAC-SHA256 verification as existing Razorpay webhooks
- **Audit trail**: Every financial operation logged in existing `AuditEvent` + `CommissionAuditLog`

---

## 15. Monitoring & Alerting

| Event | Severity | Action |
|-------|----------|--------|
| Franchisee KYC rejected | Warning | Notify admin |
| Transfer failed 3+ times | Critical | Alert admin, pause franchise transfers |
| Settlement entry stuck PENDING > 24h | Warning | Alert admin |
| Commission rate changed | Info | Audit log |
| Franchisee deactivated | Warning | Audit log + final settlement |
| Transfer reversal initiated | Info | Audit log |
| Franchisee activated (KYC approved) | Info | Process pending transfers |

Integrates with existing Sentry + New Relic monitoring.

---

## 16. Implementation Phases

### Phase 0: GST Billing (Prerequisite)
1. Add `gst_percent` to Tariff model + migration
2. Add `energy_charge`, `gst_amount`, `total_billed` to Transaction model + migration
3. Update `WalletService.calculate_billing_amount()` to include GST
4. Update `WalletService.process_transaction_billing()` to deduct energy + GST
5. Update `QRPaymentService.process_qr_session_billing()` refund calculation with GST
6. Update `QRPaymentService.check_budget_and_auto_stop()` to include GST in cost check
7. Update customer-facing billing display (frontend)
8. Backfill existing tariffs with `gst_percent = 18.00`

### Phase 1: Core Franchisee Module
1. Database models + Aerich migration (Franchisee, CommissionLedgerEntry, etc.)
2. RazorpayService Route API extensions
3. FranchiseeSettlementService (calculation + transfer)
4. FranchiseeOnboardingService (self-service KYC flow)
5. Webhook handler updates (account.*, transfer.*)
6. Admin CRUD router (`/api/admin/franchisees/*`)
7. Settlement router (`/api/admin/settlements/*`)
8. Integration into StopTransaction (hook after billing)
9. Retry logic in BillingRetryService

### Phase 2: Franchisee Portal
10. Franchisee authentication + middleware
11. Franchisee backend router (`/api/franchisee/*`)
12. Frontend: franchisee dashboard + station management
13. Frontend: settlement history + invoice downloads

### Phase 3: Reporting & Invoicing
14. Invoice generation service + PDF
15. GST/TDS reporting APIs
16. Admin reporting dashboard
17. Frontend: admin franchisee management pages

---

## 17. Testing Strategy

### Simulator
- `backend/simulators/ocpp_simulator_franchisee.py` -- simulate charging sessions on franchisee-owned chargers, verify settlement creation and transfer initiation

### Unit Tests
- Settlement calculation with various scenarios (QR, wallet, zero energy, min amount)
- Commission rate freezing
- TDS calculation at different rates
- Idempotency (duplicate calls)

### Integration Tests
- Full flow: create franchisee -> submit KYC -> assign station -> charge session -> verify settlement
- Webhook handling (mock Razorpay webhooks)
- Franchisee portal access control (can access own, cannot access others)
- Transfer retry after failure

### Manual Verification
- Razorpay test mode: create real linked accounts in sandbox
- Verify transfer appears in Razorpay dashboard
- Verify settlement formula with real numbers matches this spec
