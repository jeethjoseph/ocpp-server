# Internal-role sessions: skip wallet billing + budget cap, audit + metric the skip

Status: ready-for-agent

## What to build

Today an ADMIN or FRANCHISEE who starts a charging session with `energy > 0` triggers `WalletService.process_transaction_billing`. If they have no wallet, it sets `transaction_status = BILLING_FAILED` and the retry service hammers it every 30 minutes forever (this surfaced as the user-12 incident on 2026-05-19). If they DO have a wallet (legacy/backfilled), `WalletSessionService.cache_session_on_start` caches a budget snapshot, the MeterValues handler enforces it, and the session is remote-stopped within seconds when balance is ₹0.

Both behaviours are wrong under the new policy: an **Internal-role Session** (per CONTEXT.md and ADR 0004) is purely operational. No `WalletTransaction`, no budget cap, no `BILLING_FAILED`.

### Plan

- **`WalletService.process_transaction_billing`** — after loading the transaction, look up `transaction.user.role`. If in `INTERNAL_ROLES`:
  - Set `transaction_status = COMPLETED`.
  - Write an `audit_log` row: `action="transaction.status_changed"`, `changes={"new_status": "COMPLETED", "trigger": "InternalRoleSkip", "reason": "Wallet billing skipped — internal-role session per policy", "role": user.role.value}`.
  - Increment `Custom/Wallet/InternalRoleSkipped`.
  - Return success-but-skipped (existing return shape: `(True, "Skipped — internal role", Decimal("0.00"), None)`).
- **`WalletSessionService.cache_session_on_start`** — look up the user role for the wallet's user. If in `INTERNAL_ROLES`, increment `Custom/WalletSession/InternalRoleSkipped` and return without caching the session. The MeterValues budget check naturally short-circuits because no cache row exists.
- **Update the now-wrong comment at `invoice_service.py:213-220`** — delete the "*These deduct from the initiator's wallet*" clause; replace with the post-ADR-0004 semantic.

The role check uses `INTERNAL_ROLES` from `core/roles.py` (issue 01 of this batch). No call-site changes — both wallet services become role-aware internally per Q2 of the grilling.

### Out of scope

- Wallet creation gating at the Clerk webhook → covered by issue 03.
- Existing 7 backfilled wallets → covered by issue 03.
- QR-funded sessions for internal-role users — per CONTEXT.md's working assumption, this flow doesn't occur in practice. No special handling.

See [ADR 0004](../../../docs/adr/0004-internal-role-sessions-are-operational.md) and [CONTEXT.md](../../../CONTEXT.md) "Internal-role Session" / "Internal-role User".

## Acceptance criteria

- [ ] An ADMIN-role wallet-funded charging session with `energy > 0` ends with `transaction_status = COMPLETED`, no `WalletTransaction` row, and no `BILLING_FAILED` state at any point in its lifecycle.
- [ ] An audit_log row exists for that session with `trigger = "InternalRoleSkip"` and a reason mentioning the policy.
- [ ] `Custom/Wallet/InternalRoleSkipped` increments by 1 per skip.
- [ ] An ADMIN-role StartTransaction does NOT create a `wallet_session:{txn_id}` Redis cache entry. `Custom/WalletSession/InternalRoleSkipped` increments by 1.
- [ ] The billing_retry_service no longer picks up the session (it only retries `BILLING_FAILED`).
- [ ] USER-role sessions are unchanged — existing test fixtures and assertions all pass.
- [ ] FRANCHISEE-role sessions follow the same path as ADMIN sessions (same skip, same metrics, same audit shape).
- [ ] The comment block at `invoice_service.py:213-220` no longer claims "These deduct from the initiator's wallet."

## Blocked by

Issue 01 (shared `INTERNAL_ROLES` module).
