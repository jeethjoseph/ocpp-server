# Manual settlement resolution uses the audit log, not a new enum value

When an admin marks a stuck `CommissionLedgerEntry` as terminal — either `BELOW_THRESHOLD` (sub-floor payout the Razorpay Route API will never accept) or `SETTLED` (resolved out-of-band, e.g. franchisee paid via direct bank transfer) — the resolution is recorded in `audit_log` with a distinct `action` (`settlement.mark_below_threshold`, `settlement.manual_settle`) and the row simply transitions to the existing terminal status. There is **no `MANUAL_SETTLED` enum value, no `manually_resolved_by` column, no `manual_resolution_note` field on `commission_ledger_entry`**.

A row that reads `settlement_status = 'SETTLED'` with `razorpay_transfer_id IS NULL` and a matching `audit_log` entry is, by construction, a manually-settled row. The audit log is load-bearing for compliance — it already captures actor, timestamp, and the free-form note the admin typed.

## Considered alternatives

- **New enum value `MANUAL_SETTLED`.** Distinguishes manual from Razorpay-driven resolutions at a glance in the schema. Rejected: requires an Aerich migration, a backfill plan for any historical rows manually closed before the value existed, and dual code paths in every place that branches on `SETTLED` (reporting queries, franchisee portal views, GST invoice eligibility). The audit-log query — `SELECT * FROM audit_log WHERE action IN ('settlement.mark_below_threshold', 'settlement.manual_settle')` — answers the same question without schema churn.
- **New column `manual_resolution_note TEXT NULL` on `commission_ledger_entry`.** Lets reports surface the note inline. Rejected: ~99% of rows would be NULL forever, the column duplicates `audit_log.changes->>'note'`, and joins on `audit_log` by `entity_id` are already the canonical pattern for "who did what to this entry."
- **No backend record at all, just a status flip.** Rejected immediately: every other admin-initiated state change (`/hold`, `/release`, `/retry-failed`) already logs an audit row. Skipping it for terminal resolution is the worst possible asymmetry — these are the highest-stakes admin actions because they're irreversible from the UI.

## Consequences

- A future contributor reading `SettlementStatusEnum` will not see "manual" as a first-class concept. This ADR is the artifact that tells them why — every state in the enum reflects what happened to the **money**, not who decided it. `SETTLED` means the franchisee has the funds, regardless of the rails that moved them.
- Searching for "all manually resolved settlements in the last quarter" requires an `audit_log` query, not a `commission_ledger_entry` query. The two new actions (`settlement.mark_below_threshold`, `settlement.manual_settle`) are stable identifiers — do not rename them without a migration of historical audit rows.
- Idempotency on the new endpoints relies on checking `settlement_status` only; a re-clicked Mark SETTLED on an already-`SETTLED` row returns 200 and does **not** write a second audit entry. The first audit entry is the source of truth for who originally resolved it.
- `settled_at` is set to `now()` on first transition only; subsequent idempotent calls preserve it. Admins cannot back-date — period-close reports stay consistent with when the resolution was actually decided.
- If a future requirement makes "manual vs Razorpay" queryable at the row level a hot path (e.g. a reconciliation report runs daily and audit-log joins become a bottleneck), revisit this ADR. The reversal cost is a migration that backfills a derived column from `audit_log` and a coordinated cutover — non-trivial but not catastrophic.
