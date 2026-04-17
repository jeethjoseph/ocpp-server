# Franchisee Module - Testing Guide

**Date:** 2026-04-16
**Branch:** `65-franchisee-ownership-module`
**Backend:** http://localhost:8000 (Swagger: http://localhost:8000/docs)
**Frontend:** http://localhost:3000

---

## Prerequisites

1. Docker containers running: `docker compose up -d`
2. An admin account logged into the frontend (e.g., `admin@ocpp.com`)
3. At least one charging station exists (26 stations currently in DB)

### Getting an Auth Token

All API calls require a Clerk JWT. The easiest way:

1. Log into the frontend as admin at http://localhost:3000
2. Open browser DevTools > Network tab
3. Find any `/api/` request and copy the `Authorization: Bearer <token>` header
4. Use that token in all curl commands below

```bash
# Set this once for your session
export TOKEN="Bearer ey..."
```

---

## Phase 1: Franchisee CRUD + Station Assignment

### Test 1.1: Create a Franchisee

```bash
curl -s -X POST http://localhost:8000/api/admin/franchisees \
  -H "Authorization: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "business_name": "Green EV Charging Pvt Ltd",
    "contact_name": "Rahul Sharma",
    "contact_email": "rahul@greenevc.com",
    "contact_phone": "9876543210",
    "commission_percent": 20,
    "tds_rate_percent": 10,
    "notes": "Test franchisee for development"
  }' | python3 -m json.tool
```

**Expected:**
- Status 200
- Response includes `id`, `status: "DRAFT"`, `station_count: 0`
- A User with `role: FRANCHISEE` is created (check Users page in admin)
- CommissionAuditLog entry created with `reason: INITIAL_SETUP`

**Verify in DB:**
```bash
docker exec ocpp-backend python -c "
import asyncio
from tortoise import Tortoise
from tortoise_config import TORTOISE_ORM
async def check():
    await Tortoise.init(config=TORTOISE_ORM)
    from models import Franchisee, User, CommissionAuditLog
    f = await Franchisee.filter(contact_email='rahul@greenevc.com').first()
    print(f'Franchisee: id={f.id}, status={f.status}, commission={f.commission_percent}')
    u = await User.filter(email='rahul@greenevc.com').first()
    print(f'User: id={u.id}, role={u.role}')
    logs = await CommissionAuditLog.filter(franchisee_id=f.id).count()
    print(f'Audit logs: {logs}')
    await Tortoise.close_connections()
asyncio.run(check())
"
```

### Test 1.2: List Franchisees

```bash
curl -s http://localhost:8000/api/admin/franchisees \
  -H "Authorization: $TOKEN" | python3 -m json.tool
```

**Expected:** Paginated list with the franchisee created above.

### Test 1.3: Search and Filter

```bash
# Search by name
curl -s "http://localhost:8000/api/admin/franchisees?search=Green" \
  -H "Authorization: $TOKEN" | python3 -m json.tool

# Filter by status
curl -s "http://localhost:8000/api/admin/franchisees?status=DRAFT" \
  -H "Authorization: $TOKEN" | python3 -m json.tool
```

### Test 1.4: Get Franchisee Detail

```bash
# Replace 1 with actual franchisee ID from Test 1.1
curl -s http://localhost:8000/api/admin/franchisees/1 \
  -H "Authorization: $TOKEN" | python3 -m json.tool
```

### Test 1.5: Update Franchisee

```bash
curl -s -X PUT http://localhost:8000/api/admin/franchisees/1 \
  -H "Authorization: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "address": "123 Green Lane, Kochi, Kerala 682001",
    "gstin": "32AABCG1234F1Z5",
    "pan_number": "AABCG1234F",
    "state": "Kerala",
    "state_code": "32"
  }' | python3 -m json.tool
```

### Test 1.6: Update Commission (with Audit Trail)

```bash
curl -s -X PUT http://localhost:8000/api/admin/franchisees/1/commission \
  -H "Authorization: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "new_percent": 18.5,
    "reason": "CONTRACT_RENEWAL",
    "effective_from": "2026-05-01",
    "notes": "Reduced commission for Q2"
  }' | python3 -m json.tool
```

**Expected:** `previous: 20.00, new: 18.5`

### Test 1.7: View Commission History

```bash
curl -s http://localhost:8000/api/admin/franchisees/1/commission-history \
  -H "Authorization: $TOKEN" | python3 -m json.tool
```

**Expected:** Two entries -- INITIAL_SETUP (20%) and CONTRACT_RENEWAL (18.5%)

### Test 1.8: Assign Stations

```bash
# Assign stations 1 and 2
curl -s -X POST http://localhost:8000/api/admin/franchisees/1/stations \
  -H "Authorization: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"station_ids": [1, 2]}' | python3 -m json.tool
```

**Expected:** `"Assigned 2 station(s) to franchisee"`

**Verify:**
```bash
curl -s http://localhost:8000/api/admin/franchisees/1/stations \
  -H "Authorization: $TOKEN" | python3 -m json.tool
```

### Test 1.9: Unassign Station

```bash
curl -s -X DELETE http://localhost:8000/api/admin/franchisees/1/stations/2 \
  -H "Authorization: $TOKEN" | python3 -m json.tool
```

### Test 1.10: Duplicate Assignment Guard

```bash
# Try to assign station 1 to a different franchisee (create one first)
# Should fail with 409 if station 1 is already assigned
```

### Test 1.11: Update Status

```bash
curl -s -X PUT "http://localhost:8000/api/admin/franchisees/1/status?status=ACTIVE" \
  -H "Authorization: $TOKEN" | python3 -m json.tool
```

### Test 1.12: Role-Based Access Denial

```bash
# Try to access admin franchisee endpoint with a USER-role token
# Should return 403
curl -s http://localhost:8000/api/admin/franchisees \
  -H "Authorization: Bearer <user_token>" | python3 -m json.tool
```

---

## Phase 1 Frontend Tests

### Test 1.F1: Admin Franchisee List Page
1. Log in as admin at http://localhost:3000
2. Navigate to http://localhost:3000/admin/franchisees
3. **Verify:** "Franchisees" appears in the admin navigation bar
4. **Verify:** Table shows the franchisee created via API
5. **Verify:** Search box filters by name/email
6. **Verify:** Status dropdown filters by status
7. Click "Add Franchisee" button
8. Fill in the form and submit
9. **Verify:** New franchisee appears in the list

### Test 1.F2: Admin Franchisee Detail Page
1. Click on a franchisee name in the list
2. **Verify:** Business details card shows all fields
3. **Verify:** Commission/TDS cards show current rates
4. **Verify:** Station count matches assigned stations
5. Click "Assign Station" -- select a station from dropdown
6. **Verify:** Station appears in the assigned stations table
7. Click unlink icon to unassign a station
8. Click "Update Commission" -- fill in new rate
9. **Verify:** Commission history table updates

---

## Phase 2: Settlement Engine

### Test 2.1: Settlement for VoltLync-Owned Station (No-op)

Complete a charging session at a station that has NO franchisee assigned.

**Verify:** No `CommissionLedgerEntry` is created.

```bash
docker exec ocpp-backend python -c "
import asyncio
from tortoise import Tortoise
from tortoise_config import TORTOISE_ORM
async def check():
    await Tortoise.init(config=TORTOISE_ORM)
    from models import CommissionLedgerEntry
    count = await CommissionLedgerEntry.all().count()
    print(f'Total ledger entries: {count}')
    await Tortoise.close_connections()
asyncio.run(check())
"
```

### Test 2.2: Settlement for Franchisee-Owned Station

1. Assign a station to the test franchisee (if not done)
2. Start a charging session on a charger at that station
3. Complete the session (StopTransaction)

**Verify:**
```bash
docker exec ocpp-backend python -c "
import asyncio
from tortoise import Tortoise
from tortoise_config import TORTOISE_ORM
async def check():
    await Tortoise.init(config=TORTOISE_ORM)
    from models import CommissionLedgerEntry
    entries = await CommissionLedgerEntry.all().order_by('-created_at').limit(5)
    for e in entries:
        print(f'Entry {e.id}: txn={e.transaction_id}, gross={e.gross_amount}, '
              f'payout={e.franchisee_payout}, status={e.settlement_status}, '
              f'method={e.payment_method}, commission={e.commission_percent}%')
    await Tortoise.close_connections()
asyncio.run(check())
"
```

**Expected fields on the ledger entry:**
- `gross_amount` = total billed to customer
- `gst_collected` = GST component
- `net_excl_gst` = gross - refund - pg_fee - gst
- `platform_commission` = net_excl_gst * commission%
- `tds_amount` = net_excl_gst * tds%
- `franchisee_payout` = net_excl_gst - commission - tds - transfer_fee
- `settlement_status` = `PENDING` (Route disabled) or `TRANSFER_INITIATED`
- `idempotency_key` = `txn_{transaction_id}`

### Test 2.3: Settlement Idempotency

Call `process_settlement` twice for the same transaction:

```bash
docker exec ocpp-backend python -c "
import asyncio
from tortoise import Tortoise
from tortoise_config import TORTOISE_ORM
async def check():
    await Tortoise.init(config=TORTOISE_ORM)
    from services.franchisee_settlement_service import FranchiseeSettlementService
    from models import CommissionLedgerEntry
    # Use the latest transaction ID at a franchisee station
    # Replace with actual transaction ID
    txn_id = 1  # REPLACE
    result1 = await FranchiseeSettlementService.process_settlement(txn_id)
    result2 = await FranchiseeSettlementService.process_settlement(txn_id)
    count = await CommissionLedgerEntry.filter(transaction_id=txn_id).count()
    print(f'Result1: {result1.id if result1 else None}')
    print(f'Result2: {result2.id if result2 else None}')
    print(f'Entries for txn {txn_id}: {count} (should be 1)')
    await Tortoise.close_connections()
asyncio.run(check())
"
```

**Expected:** Both calls return the same entry. Count is 1.

### Test 2.4: Settlement Formula Verification

```bash
docker exec ocpp-backend python -c "
from decimal import Decimal
from services.franchisee_settlement_service import FranchiseeSettlementService

# Worked example from spec: QR session
result = FranchiseeSettlementService.calculate_settlement(
    gross_amount=Decimal('500.00'),
    refund_amount=Decimal('77.00'),
    pg_fee_amount=Decimal('2.50'),
    gst_collected=Decimal('63.00'),
    commission_pct=Decimal('20.00'),
    tds_pct=Decimal('10.00'),
)
for k, v in result.items():
    print(f'{k}: {v}')

# Verify: franchisee_payout should be ~249.62
"
```

### Test 2.5: Admin Settlement Endpoints

```bash
# List settlements for a franchisee
curl -s "http://localhost:8000/api/admin/franchisees/1/settlements" \
  -H "Authorization: $TOKEN" | python3 -m json.tool

# Hold a settlement
curl -s -X POST "http://localhost:8000/api/admin/franchisees/1/settlements/1/hold" \
  -H "Authorization: $TOKEN" | python3 -m json.tool

# Release a held settlement
curl -s -X POST "http://localhost:8000/api/admin/franchisees/1/settlements/1/release" \
  -H "Authorization: $TOKEN" | python3 -m json.tool

# Retry failed transfers
curl -s -X POST "http://localhost:8000/api/admin/franchisees/1/settlements/retry-failed" \
  -H "Authorization: $TOKEN" | python3 -m json.tool
```

### Test 2.6: Razorpay Route Feature Flag

```bash
# Check Route is disabled by default
docker exec ocpp-backend python -c "
from services.razorpay_service import razorpay_service
print(f'Route enabled: {razorpay_service.is_route_enabled()}')
"
```

**Expected:** `Route enabled: False` -- settlements create ledger entries but skip transfers.

---

## Phase 3: Franchisee Portal

### Test 3.1: Franchisee Login and Redirect

1. The franchisee User created in Test 1.1 needs a Clerk account. Options:
   a. **Quick test:** Update the franchisee user's `clerk_user_id` to match an existing Clerk user, and set that Clerk user's `publicMetadata.role` to `FRANCHISEE`
   b. **Proper test:** Create a new Clerk user with the franchisee email, set role in Clerk metadata

2. Log in as the franchisee user at http://localhost:3000
3. **Verify:** Automatically redirected to `/franchisee`
4. **Verify:** Navbar shows: Dashboard, Stations, Transactions, Settlements, QR Codes, Profile

### Test 3.2: Dashboard

1. Navigate to http://localhost:3000/franchisee
2. **Verify:** Shows 4 stat cards (stations, chargers, active sessions, total payout)
3. **Verify:** Status badge shows current franchisee status
4. **Verify:** Navigation links to stations, transactions, settlements

### Test 3.3: Stations

1. Navigate to http://localhost:3000/franchisee/stations
2. **Verify:** Only shows stations assigned to this franchisee
3. Click on a station name
4. **Verify:** Station detail shows charger list with status badges
5. Click on a charger name
6. **Verify:** Charger detail page with remote commands

### Test 3.4: Data Isolation

**Critical security test:** Verify a franchisee cannot see another franchisee's data.

```bash
# Create a second franchisee and assign different stations
curl -s -X POST http://localhost:8000/api/admin/franchisees \
  -H "Authorization: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "business_name": "Blue Charge Networks",
    "contact_name": "Priya Patel",
    "contact_email": "priya@bluecharge.com",
    "contact_phone": "9876543211"
  }' | python3 -m json.tool

# Assign different stations to franchisee 2
curl -s -X POST http://localhost:8000/api/admin/franchisees/2/stations \
  -H "Authorization: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"station_ids": [3, 4]}' | python3 -m json.tool
```

Then log in as franchisee 1 and verify:
- `/franchisee/stations` only shows stations 1 (not 3, 4)
- `/franchisee/stations/3` returns 404 (not franchisee 1's station)
- `/franchisee/transactions` only shows transactions at station 1's chargers

### Test 3.5: Charger Commands

1. Go to a charger detail page at `/franchisee/chargers/{id}`
2. If there's an active session, click "Remote Stop"
3. **Verify:** Stop command is sent
4. Click "Soft Reset"
5. **Verify:** Reset command is sent
6. **Verify:** Buttons are disabled while command is in progress

### Test 3.6: Role Access Guards

1. As a FRANCHISEE user, try to navigate to `/admin` or `/admin/franchisees`
2. **Verify:** Redirected to `/` (which then redirects to `/franchisee`)
3. As an ADMIN user, try to navigate to `/franchisee`
4. **Verify:** Redirected to `/`

```bash
# API-level guard: franchisee trying to access admin endpoint
curl -s http://localhost:8000/api/admin/franchisees \
  -H "Authorization: Bearer <franchisee_token>" | python3 -m json.tool
# Expected: 403 "Access denied. Required role: ADMIN"

# API-level guard: admin trying to access franchisee portal
curl -s http://localhost:8000/api/franchisee/dashboard \
  -H "Authorization: $TOKEN" | python3 -m json.tool
# Expected: 403 "Access denied. Franchisee role required."
```

### Test 3.7: Franchisee Portal Pages Checklist

| Page | URL | What to Verify |
|------|-----|----------------|
| Dashboard | `/franchisee` | Stat cards load, status badge, nav links |
| Stations | `/franchisee/stations` | Table with own stations only |
| Station Detail | `/franchisee/stations/{id}` | Station info + charger list |
| Charger Detail | `/franchisee/chargers/{id}` | Charger info + command buttons |
| Transactions | `/franchisee/transactions` | Paginated table, own station txns only |
| Transaction Detail | `/franchisee/transactions/{id}` | Billing breakdown + meter values |
| Settlements | `/franchisee/settlements` | Ledger entries with status badges |
| Profile | `/franchisee/profile` | Business info, tax, commission, KYC status |
| QR Codes | `/franchisee/qr-codes` | QR code grid for own chargers |

---

## Phase 4: GST Invoices

### Test 4.1: Invoice Generation (Automatic)

After a charging session completes at any station (franchisee-owned or VoltLync), an invoice should be auto-generated.

```bash
docker exec ocpp-backend python -c "
import asyncio
from tortoise import Tortoise
from tortoise_config import TORTOISE_ORM
async def check():
    await Tortoise.init(config=TORTOISE_ORM)
    from models import GSTInvoice
    invoices = await GSTInvoice.all().order_by('-created_at').limit(5)
    for inv in invoices:
        print(f'{inv.invoice_number}: txn={inv.transaction_id}, '
              f'supplier={inv.supplier_name}, total={inv.total_amount}, '
              f'method={inv.payment_method}')
    if not invoices:
        print('No invoices yet. Complete a charging session to trigger generation.')
    await Tortoise.close_connections()
asyncio.run(check())
"
```

### Test 4.2: Manual Invoice Generation

```bash
# Replace TRANSACTION_ID with an actual completed transaction
docker exec ocpp-backend python -c "
import asyncio
from tortoise import Tortoise
from tortoise_config import TORTOISE_ORM
async def check():
    await Tortoise.init(config=TORTOISE_ORM)
    from services.invoice_service import InvoiceService
    from models import Transaction, TransactionStatusEnum
    # Get the latest completed transaction
    txn = await Transaction.filter(
        transaction_status=TransactionStatusEnum.COMPLETED,
        energy_consumed_kwh__gt=0,
    ).order_by('-created_at').first()
    if not txn:
        print('No completed transactions with energy found')
        return
    print(f'Generating invoice for txn {txn.id}...')
    invoice = await InvoiceService.generate_invoice(txn.id)
    if invoice:
        print(f'Invoice: {invoice.invoice_number}')
        print(f'Supplier: {invoice.supplier_name}')
        print(f'Energy: {invoice.energy_consumed_kwh} kWh')
        print(f'Taxable: {invoice.total_taxable_value}')
        print(f'CGST: {invoice.cgst_amount}, SGST: {invoice.sgst_amount}')
        print(f'IGST: {invoice.igst_amount}')
        print(f'Total: {invoice.total_amount}')
        print(f'Words: {invoice.amount_in_words}')
        print(f'Payment: {invoice.payment_method}, Refund: {invoice.refund_amount}')
    else:
        print('Invoice generation returned None (zero energy or already exists)')
    await Tortoise.close_connections()
asyncio.run(check())
"
```

### Test 4.3: Sequential Invoice Numbering

Generate invoices for 2 different transactions and verify sequential numbering:

```bash
docker exec ocpp-backend python -c "
import asyncio
from tortoise import Tortoise
from tortoise_config import TORTOISE_ORM
async def check():
    await Tortoise.init(config=TORTOISE_ORM)
    from models import GSTInvoice
    invoices = await GSTInvoice.all().order_by('invoice_number')
    for inv in invoices:
        print(f'{inv.invoice_number}')
    await Tortoise.close_connections()
asyncio.run(check())
"
```

**Expected format:** `VL/{SERIES}/{FY}/{SEQ}` for VoltLync, `VL/F{id}/{SERIES}/{FY}/{SEQ}` for franchisee.

### Test 4.4: CGST+SGST vs IGST

- If supplier state code == station state code: CGST 9% + SGST 9% (both non-null)
- If different: IGST 18% (CGST/SGST should be null)

Set franchisee state_code = "32" (Kerala) and station state_code = "32" -> should get CGST+SGST.
Change one to "29" (Karnataka) -> should get IGST.

### Test 4.5: Download Invoice PDF

```bash
# Admin download
curl -s http://localhost:8000/api/admin/invoices \
  -H "Authorization: $TOKEN" | python3 -m json.tool

# Get first invoice ID, then download PDF
curl -s http://localhost:8000/api/admin/invoices/1/pdf \
  -H "Authorization: $TOKEN" \
  -o /tmp/test-invoice.pdf

# Check the PDF was created
ls -la /tmp/test-invoice.pdf
open /tmp/test-invoice.pdf  # macOS
```

**Verify PDF contains:**
- TAX INVOICE header
- Supplier name and GSTIN
- Customer identifier (UPI ID or email)
- Station and charger info
- Line items table with HSN codes (998749 for energy, 997158 for gateway)
- CGST/SGST or IGST breakdown
- Total with amount in words
- Payment method and transaction amount
- Refund info (for QR sessions)
- Legal footer

### Test 4.6: Download by Transaction ID

```bash
# Any authenticated user can download invoice for a transaction
curl -s http://localhost:8000/api/transactions/1/invoice/pdf \
  -H "Authorization: $TOKEN" \
  -o /tmp/test-invoice-by-txn.pdf
```

### Test 4.7: Franchisee Invoice List

```bash
# As franchisee user
curl -s http://localhost:8000/api/franchisee/invoices \
  -H "Authorization: Bearer <franchisee_token>" | python3 -m json.tool
```

**Expected:** Only invoices where `franchisee_id` matches the logged-in franchisee.

### Test 4.8: Invoice Idempotency

```bash
# Generate invoice twice for same transaction
docker exec ocpp-backend python -c "
import asyncio
from tortoise import Tortoise
from tortoise_config import TORTOISE_ORM
async def check():
    await Tortoise.init(config=TORTOISE_ORM)
    from services.invoice_service import InvoiceService
    from models import GSTInvoice
    inv1 = await InvoiceService.generate_invoice(1)  # REPLACE with real txn ID
    inv2 = await InvoiceService.generate_invoice(1)
    print(f'Invoice 1: {inv1.id if inv1 else None}')
    print(f'Invoice 2: {inv2.id if inv2 else None}')
    print(f'Same? {inv1 and inv2 and inv1.id == inv2.id}')
    count = await GSTInvoice.filter(transaction_id=1).count()
    print(f'Invoice count for txn 1: {count} (should be 1)')
    await Tortoise.close_connections()
asyncio.run(check())
"
```

---

## Edge Cases

### E1: Zero-Energy Session
Complete a session with 0 kWh consumed.
- **Expected:** No settlement entry, no invoice generated.

### E2: VoltLync-Owned Station
Complete a session at a station with `franchisee_id = NULL`.
- **Expected:** No settlement entry. Invoice IS generated (supplier = VoltLync).

### E3: Franchisee Not Active
Set franchisee status to `SUSPENDED`, then complete a session at their station.
- **Expected:** Settlement entry created with status `PENDING`, transfer NOT initiated.

### E4: Duplicate Franchisee Email
```bash
curl -s -X POST http://localhost:8000/api/admin/franchisees \
  -H "Authorization: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "business_name": "Duplicate Test",
    "contact_name": "Test",
    "contact_email": "rahul@greenevc.com",
    "contact_phone": "1234567890"
  }' | python3 -m json.tool
```
**Expected:** 409 "User with email rahul@greenevc.com already exists"

### E5: Assign Already-Assigned Station
```bash
# If station 1 is assigned to franchisee 1, try assigning to franchisee 2
curl -s -X POST http://localhost:8000/api/admin/franchisees/2/stations \
  -H "Authorization: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"station_ids": [1]}' | python3 -m json.tool
```
**Expected:** 409 "Stations already assigned to another franchisee: [1]"

---

## Quick Smoke Test Checklist

- [ ] Create franchisee via API
- [ ] Create franchisee via admin UI (Add Franchisee button)
- [ ] Assign stations via API
- [ ] Assign stations via admin UI detail page
- [ ] Update commission with audit trail
- [ ] Franchisee list page loads with search/filter
- [ ] Franchisee detail page loads with all sections
- [ ] Franchisee portal dashboard loads (if Clerk user configured)
- [ ] Franchisee portal stations/transactions show only own data
- [ ] Settlement entry created after charging session at franchisee station
- [ ] No settlement for VoltLync-owned station
- [ ] Invoice generated after charging session
- [ ] PDF download works and matches sample layout
- [ ] Admin cannot access /franchisee routes
- [ ] Franchisee cannot access /admin routes
- [ ] USER cannot access /admin or /franchisee routes
