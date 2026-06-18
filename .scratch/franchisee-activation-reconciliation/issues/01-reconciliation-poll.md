Status: ready-for-agent

# Periodic reconciliation poll for stuck KYC_SUBMITTED franchisees

## Context

On 2026-05-30 we found franchisee #1 (R Shyam Shankar, station SARADHY TOWERS) sitting at `status=KYC_SUBMITTED` for ~16 hours despite Razorpay having already activated the Route product. The inline PATCH response on 2026-05-28 17:46:41 returned `activation_status: "activated"`, `requirements: []`, but our state machine ignored it and waited for an `account.activated` webhook that Razorpay never fired (verified: zero rows in `webhook_event` for `acc_Sum1WSDEGbyNL1`).

Three QR-funded sessions (ledger entries #1, #2, #3) at this station accumulated as PENDING ledger rows because `FranchiseeSettlementService.initiate_transfer` gates on `franchisee.status == ACTIVE`. The retry sweep explicitly skips PENDING, so the rows would have stayed stuck indefinitely.

**The inline-promotion fix (this branch, `services/franchisee_onboarding_service._promote_on_activated_response`) handles ~95% of cases** by reading the synchronous PATCH response and promoting in the same transaction. This issue is the remaining 5% — anything that bypasses our PATCH path:

- Razorpay-dashboard admin actions that flip the account state out-of-band.
- A transient network error during our PATCH where Razorpay processed the request but we never saw the response.
- Activation that happens later (e.g. requirements cleared after KYC review) where we never re-PATCH.
- Backfill for franchisees onboarded **before** the inline-promotion fix shipped.

## What to build

A background scheduler task that periodically polls Razorpay for stuck `KYC_SUBMITTED` (and optionally `KYC_UNDER_REVIEW`, `KYC_NEEDS_CLARIFICATION`) franchisees and promotes any that have flipped to activated on Razorpay's side.

### Behaviour

Every `FRANCHISEE_ACTIVATION_POLL_INTERVAL_SECONDS` (default **3600** — once per hour; configurable to as low as 600 for testing), the task:

1. Selects all `franchisee` rows where `status IN ('KYC_SUBMITTED', 'KYC_UNDER_REVIEW', 'KYC_NEEDS_CLARIFICATION')` AND `razorpay_product_id IS NOT NULL`.
2. For each, calls `razorpay_service.fetch_product_configuration(razorpay_account_id, razorpay_product_id)`.
3. Passes the response into the existing `_promote_on_activated_response(franchisee_id, result, source='reconciliation_poll')` helper. The helper is already idempotent — no-op if already ACTIVE, no-op if requirements outstanding.
4. After promoting, calls `FranchiseeSettlementService.retry_failed_transfers(franchisee_id=...)` so any FAILED/ON_HOLD entries for that franchisee that were waiting on activation can drain immediately. **PENDING entries still need a separate sweep** — see "Open question" below.

### Wiring

Mirror the existing `FranchiseePayoutRetryService` pattern at `backend/services/franchisee_payout_retry_service.py`:

- New file `backend/services/franchisee_activation_reconciliation_service.py`
- `class FranchiseeActivationReconciliationService` with `start()` / `stop()` / `_loop()`
- Module-level `start_franchisee_activation_reconciliation_service()` / `stop_*` functions
- Gated on `RAZORPAY_ROUTE_ENABLED == "true"` (same as the payout retry service)
- Started from `main.py` startup, stopped from shutdown — same pattern as the payout retry

### Open question to resolve during implementation

**PENDING ledger entries are not picked up by `retry_failed_transfers`.** That sweep explicitly filters on `settlement_status IN (FAILED, ON_HOLD)`. So after a franchisee is promoted via the reconciliation poll, the historical PENDING rows still need manual settlement.

Two options:

**(A) Extend `retry_failed_transfers` to also re-process PENDING rows for franchisees that just got activated.** Cleanest but changes the contract of an existing function — risks accidentally retrying entries that genuinely should not progress.

**(B) Add a one-shot "process pending for franchisee X" helper that the reconciliation loop calls only after promoting.** Targets the exact case (promotion just happened, so PENDING means "was created during the KYC_SUBMITTED window"). Smaller blast radius.

Recommend (B). Implementer should confirm with reviewer before coding.

## Acceptance criteria

- [ ] `FranchiseeActivationReconciliationService` exists, started from `main.py` startup gated on `RAZORPAY_ROUTE_ENABLED=true`
- [ ] Loop interval is `FRANCHISEE_ACTIVATION_POLL_INTERVAL_SECONDS` env var, default 3600, clamped to >= 60
- [ ] On each tick, fetches product config for each stuck franchisee and routes the response through `_promote_on_activated_response`
- [ ] After a successful promotion, drains the just-promoted franchisee's stuck rows per the option chosen above (default recommendation: option B)
- [ ] No-op when there are zero stuck franchisees (no Razorpay API calls)
- [ ] Errors on a single franchisee do NOT abort the loop — log and continue
- [ ] Unit test: when fetch_product_configuration returns activated+requirements=[], the franchisee gets promoted and its PENDING rows are drained
- [ ] Unit test: when fetch_product_configuration raises (Razorpay API down), the franchisee row is left untouched and the loop continues
- [ ] Counter metric `Custom/Franchisee/ActivationReconciled` incremented per promotion (long-term tracking of how often this safety net actually catches something — high value means the inline path is failing, low value means it's working)

## Out of scope

- Backfill of historical KYC_SUBMITTED franchisees beyond what the poll naturally picks up over its first few ticks
- Reconciling franchisees that moved from KYC_UNDER_REVIEW → KYC_NEEDS_CLARIFICATION without a webhook (different state-change semantics — separate issue if it becomes a pattern)
- Any UI surface for the reconciliation status (admin can already see status on the franchisee detail page)

## Blocked by

The inline-promotion fix on this branch (`_promote_on_activated_response` helper + wiring into `submit_bank_details` + `submit_kyc`) must land first. This issue is the belt-and-braces complement.
