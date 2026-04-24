# Razorpay Route — Production Deployment Runbook

One-time checklist for enabling Razorpay Route on a new environment (staging or prod). Work top to bottom. Each section is independent and can be paused/resumed.

**Assumes:** Route is already approved by Razorpay for the partner account (confirmed via Razorpay ticket, e.g. #18765145). If Route still reads as "Locked" in the Razorpay dashboard sidebar, stop here and complete the compliance review first.

---

## 1. Webhook event subscriptions

In **Razorpay Dashboard → Settings → Webhooks → edit the environment's endpoint** (`https://<env>/webhooks/razorpay`), tick these events:

### Payments (likely already subscribed)
- [ ] `payment.captured`
- [ ] `payment.failed`
- [ ] `order.paid`

### QR codes (likely already subscribed)
- [ ] `qr_code.credited`

### Refunds — **required for Route**
- [ ] `refund.processed`
- [ ] `refund.failed`

### Route — Linked account lifecycle
- [ ] `account.activated`
- [ ] `account.activated_kyc_pending`
- [ ] `account.instantly_activated`
- [ ] `account.under_review`
- [ ] `account.needs_clarification`
- [ ] `account.rejected`
- [ ] `account.updated`

### Route — Transfers
- [ ] `transfer.processed`
- [ ] `transfer.failed`

### Route — Settlements (money arriving at franchisee's bank)
- [ ] `settlement.processed`

### Product configuration (optional, monitoring only)
- [ ] `product.route.under_review`
- [ ] `product.route.activated`
- [ ] `product.route.needs_clarification`
- [ ] `product.route.rejected`

### Events we do NOT subscribe to — documented absence

Razorpay does not expose webhooks for these states even though they show up in status fields; they are reconciled via polling the account entity on `account.updated`:
- `account.suspended`
- `account.funds_onhold` / `account.funds_unhold`

Transfer reversals don't have a dedicated event either — when you reverse a transfer, the reversal is reflected in the transfer entity's `amount_reversed` / `status` fields, not broadcast.

### Save and verify
After ticking, save the webhook. The webhook secret does **not** rotate on edit — no env change needed. Then:
- Click **Send test event** on any one event (e.g. `settlement.processed`) and confirm a `200 OK` in the Razorpay webhook log plus a row in our `webhook_event` table with `status='processed'`.

---

## 2. Environment variables

In `backend/.env.<env>`:

```env
# Route gate
RAZORPAY_ROUTE_ENABLED=true

# Tunables (optional — shown with defaults)
MINIMUM_TRANSFER_AMOUNT=1.00
MAX_TRANSFER_RETRIES=3
```

**Remove if present** (no longer used after April 2026 audit):
```env
RAZORPAY_TRANSFER_FEE_PERCENT=0.25    # deprecated — do not set
```

Live vs test keys are unchanged — staging and prod already share live Razorpay keys per `CLAUDE.md`. Dev uses `rzp_test_*` keys.

---

## 3. Database migration

Single migration `20_20260418073434_add_route_transfer_gates_and_refund_tracking.py`:

```bash
docker exec ocpp-backend aerich upgrade
```

Adds:
- `franchisee.transfers_enabled BOOL NOT NULL DEFAULT TRUE`
- `franchisee.funds_on_hold BOOL NOT NULL DEFAULT FALSE`
- `qr_payment.refund_processed_at TIMESTAMPTZ`
- `qr_payment.refund_failure_reason TEXT`
- Index on `qr_payment.razorpay_refund_id`

Safe on a live table (all columns defaulted or nullable).

---

## 4. Legacy QR cleanup

Before enabling Route in an environment that previously ran franchisee-scoped QRs:

```sql
SELECT id, charger_id, owner_razorpay_account_id
FROM charger_qr_code
WHERE is_active = true AND owner_razorpay_account_id IS NOT NULL;
```

Any rows returned are still routing payments directly to a franchisee's linked account. With the new platform-first flow, these break — the platform never sees the money but tries to transfer from its balance. **Must be regenerated before flipping `RAZORPAY_ROUTE_ENABLED=true` in that environment.**

For each row:
```bash
curl -X POST https://<env>/api/admin/qr-codes/<qr_id>/regenerate \
  -H "Authorization: Bearer <admin_jwt>"
```

Then print fresh QR stickers and coordinate station visits to swap. This is a field operation, not just a code deploy.

---

## 5. Franchisee onboarding (per franchisee)

1. Admin logs into `/admin/franchisees/<id>`.
2. Click **Edit** on the Business Details card. **Required before onboarding:**
   - Business Type (one of: Individual / Proprietorship / Partnership / Private Limited / LLP)
   - Contact Name
   - Contact Phone (valid 10-digit number)
3. (Optional but recommended before first payout) PAN, GSTIN, State, State Code.
4. Click **Start Razorpay onboarding**. Backend hits `POST /api/admin/franchisees/<id>/onboard-razorpay`.
   - Expected: HTTP 200 with `id: "acc_..."` in the response and the account status reads `created`.
   - If HTTP 400 with "business_type must be set..." — step 2 was skipped.
5. Fill **bank account details** (Beneficiary Name, IFSC, Account Number) in the same Business Details edit dialog. These are required for Step 7.
6. In the **Stakeholders** card, click **Add Stakeholder** and register the proprietor/director (Name + Email are required; Phone and PAN optional). Razorpay needs at least one stakeholder before KYC can be submitted.
7. Click **Submit for KYC**. Backend hits `POST /api/admin/franchisees/<id>/submit-kyc` — creates a product config, submits bank settlements, and returns the current `activation_status` + `requirements[]`. Account moves from `created` → `needs_clarification` / `under_review`.
   - Razorpay does NOT auto-email franchisees for this flow on your current partner setup. Once the account status becomes `activated`, toggle **Dashboard Access** on in the Razorpay partner dashboard (manual step — no API) if the franchisee needs dashboard login.
8. Razorpay's human review then advances the account. Our webhook handlers advance `Franchisee.status` through:
   - `account.activated_kyc_pending` → `KYC_UNDER_REVIEW`, `transfers_enabled=false`
   - `account.under_review` → `KYC_UNDER_REVIEW`
   - `account.needs_clarification` → `KYC_NEEDS_CLARIFICATION` (admin prompts franchisee to fix)
   - `account.activated` / `account.instantly_activated` → `ACTIVE`, `transfers_enabled=true`
   - `account.rejected` → back to `DRAFT`, `transfers_enabled=false`
9. Once `status=ACTIVE`, the franchisee can receive Route transfers.

---

## 6. End-to-end verification (per environment)

Run against ONE pilot franchisee whose status is `ACTIVE`:

1. Assign at least one station + charger to that franchisee.
2. Confirm the charger has a platform-owned QR:
   ```sql
   SELECT id, owner_razorpay_account_id FROM charger_qr_code
   WHERE charger_id = <pilot_charger_id> AND is_active = true;
   ```
   `owner_razorpay_account_id` should be `NULL`. If not, regenerate (section 4).
3. Have a customer (or yourself) do a real small-value charging session via QR scan.
4. After `StopTransaction`, expect this sequence within ~60 seconds:
   1. `QRPayment.status = COMPLETED` or `REFUNDED` (for partial-amount refund of unused balance)
   2. `CommissionLedgerEntry` row created, `settlement_status = TRANSFER_INITIATED`
   3. `transfer.processed` webhook → `settlement_status = TRANSFER_PROCESSED`, `transfer_processed_at` stamped
   4. `settlement.processed` webhook (typically T+1 or T+2 from the transfer) → `settlement_status = SETTLED`, `settled_at` stamped, `transfer_fee` populated with Razorpay's actual fee
5. Sanity-check on the Razorpay dashboard: **Route → Transfers** should show the transfer with `status=processed` and the correct amount.

If step 4.2 fails with "insufficient balance", it means the refund ate the captured funds before the transfer could execute. Unlikely but flag it — possible rebalancing needed in `process_qr_session_billing` → `initiate_transfer` ordering.

---

## 7. Monitoring for the first 48h

Watch:

```sql
-- Failed webhook deliveries
SELECT event_type, count(*) FROM webhook_event
WHERE source='RAZORPAY' AND status='failed'
  AND created_at > now() - interval '1 day'
GROUP BY event_type;

-- Stuck transfers (initiated but no processed webhook)
SELECT id, razorpay_transfer_id, transfer_initiated_at
FROM commission_ledger_entry
WHERE settlement_status = 'TRANSFER_INITIATED'
  AND transfer_initiated_at < now() - interval '30 minutes';

-- Failed transfers at max retry count (manual intervention needed)
SELECT id, franchisee_id, failure_reason
FROM commission_ledger_entry
WHERE settlement_status = 'FAILED'
  AND retry_count >= 3;

-- Refunds that haven't reached processed state
SELECT id, razorpay_refund_id, razorpay_payment_id
FROM qr_payment
WHERE razorpay_refund_id IS NOT NULL
  AND refund_processed_at IS NULL
  AND created_at < now() - interval '1 day';
```

---

## 8. Kill switches

| Scenario | Action |
|---|---|
| Full stop — no transfers at all | Set `RAZORPAY_ROUTE_ENABLED=false` in env, restart backend. Refunds and QR payments still work. |
| Stop one franchisee | Set `UPDATE franchisee SET transfers_enabled=false WHERE id=<id>;` — new settlements for them go to `ON_HOLD`. Re-enable by flipping the flag back and calling the retry-failed-settlements admin endpoint. |
| Pause a single already-initiated transfer | Admin endpoint `POST /api/admin/franchisees/<fid>/settlements/<entry_id>/hold`. |

---

## Rollback

If a production rollout goes wrong:

1. `RAZORPAY_ROUTE_ENABLED=false` + restart — all transfer attempts stop. Webhooks still process (idempotent).
2. Existing ledger entries stay in their current state. Retry endpoint works when you re-enable.
3. Migration is forward-compatible with the old code path (extra columns are ignored by old binaries). Safe to roll back code without migration downgrade.

---

## Related

- Architecture: [`docs/v1/comprehensive-architecture-documentation.md`](./v1/comprehensive-architecture-documentation.md) — Route section
- LLM context: [`docs/v1/llm-context-document.md`](./v1/llm-context-document.md) — service entries for `razorpay_service` and `franchisee_settlement_service`
- Franchisee module spec: [`docs/v1/franchisee-module-specification.md`](./v1/franchisee-module-specification.md)
