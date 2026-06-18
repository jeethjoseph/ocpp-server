# Resolve stuck commission-ledger entries for franchisee 2

Status: ready-for-human — **RESOLVED on investigation (self-healed), no action needed**

## Investigation outcome (2026-06-11, prod read-only via SSM)

Franchisee 2 (`MUHAMMED SADIQ`, `acc_Sv4ajWJPfN39Wb`, status `ACTIVE`, `transfers_enabled=t`) has exactly **2** commission-ledger entries, and both are now healthy:

| id | settlement_status | retry_count | transfer_initiated_at | razorpay_transfer_id | payout |
|----|----|----|----|----|----|
| 15 | `TRANSFER_PROCESSED` | 0 | 2026-06-04 09:38 | `trf_SxVWsOm1fmCZvF` | ₹2.99 |
| 24 | `TRANSFER_PROCESSED` | 0 | 2026-06-06 14:06 | `trf_SyNA1P9IxwbqmT` | ₹14.35 |

They were stuck in `TRANSFER_INITIATED` (the known gap — payout fired but the Razorpay transfer-status webhook hadn't landed yet, which `build_stuck_filter` flags after 24h). Both have since progressed to `TRANSFER_PROCESSED` with transfer IDs set. **No money is stuck; nothing to fix.** The historical Sentry warnings (OCPP-BACKEND-3) were the detector correctly flagging the transient `TRANSFER_INITIATED` window; issue 07's dedup/cooldown prevents the repeat-every-sweep spam going forward.

Recommend closing. (Optional: confirm the detector emits no further franchisee-2 alerts on its next sweep.)

---


Sentry: OCPP-BACKEND-3 — `Stuck franchisee payouts: 2 entries for franchisee 2` (warning)

## What to build

This is an operational/data-resolution task, not a code change. The stuck-payout detector reports that franchisee 2 has 2 `CommissionLedgerEntry` rows stuck past the threshold with transfer retries exhausted. These represent real payouts that have not settled.

A human with production access needs to:

1. Identify the 2 stuck `CommissionLedgerEntry` rows for franchisee 2 and their `settlement_status` / failure reasons.
2. Determine why they are stuck (e.g. Razorpay Route account state — see the `account.delete`/subcategory and RBI-disclosure notes; retry exhaustion; invalid linked account).
3. Resolve them: re-trigger the transfer if the underlying cause is fixed, or mark them appropriately if they are genuinely unrecoverable.
4. Confirm the detector stops reporting franchisee 2 after resolution.

## Acceptance criteria

- [ ] Root cause of the 2 stuck entries for franchisee 2 is documented (status, failure reason, Razorpay account state).
- [ ] Each stuck entry is either successfully settled/retried or explicitly closed out with a recorded reason.
- [ ] The detector no longer reports franchisee 2 as stuck on subsequent passes.
- [ ] Findings noted in this issue's Comments for audit.

## Blocked by

None - can start immediately. (Independent of issue 07; the dedup fix changes alert frequency, not the underlying stuck data.)
