# Webhook user-creation role gate + delete legacy internal-role wallets

Status: ready-for-agent

## What to build

Two related changes that close the creation-side hole behind issue 02's runtime skip.

### Gate the webhook wallet creation on role

`routers/webhooks.py:handle_user_created` unconditionally creates a wallet on the new-user branch (line 195: `await Wallet.create(user=user)`). Under ADR 0004 internal-role users don't need wallets. Gate the creation on `user_role not in INTERNAL_ROLES`. USER-role onboarding is unchanged.

The existing-user branch of that webhook (line 142-173) already never creates a wallet — that's correct under the new policy because internal-role users don't need one.

### Delete the 7 backfilled wallets

On 2026-05-19 a manual SQL backfill created wallets for 7 ADMIN/FRANCHISEE users to stop the user-12 retry storm. Per Q4 of the grilling (option b), these are deleted now that issue 02's runtime skip makes them harmless and the creation gate ensures none get added going forward.

One-shot SQL, idempotent:
```sql
DELETE FROM wallet
 WHERE user_id IN (
   SELECT id FROM app_user WHERE role IN ('ADMIN', 'FRANCHISEE')
 );
```

Runs on dev, staging, and (when deployed) prod. No migration needed — this is one-shot data cleanup, not a schema change. Document the run in the PR description so ops knows it happened.

### Out of scope

- Runtime billing/budget skip behaviour → issue 02.
- Promotion/demotion edge cases (USER → ADMIN, ADMIN → USER) — the existing lazy wallet creation at `routers/wallet_payments.py:128` handles the demotion case on first top-up attempt. No new handling needed.

See [ADR 0004](../../../docs/adr/0004-internal-role-sessions-are-operational.md).

## Acceptance criteria

- [ ] A new ADMIN-role user arriving via Clerk `user.created` webhook has no `wallet` row created.
- [ ] A new FRANCHISEE-role user via the same webhook has no `wallet` row created.
- [ ] A new USER-role user via the same webhook still has a wallet (regression guard for the happy path).
- [ ] After the one-shot SQL: `SELECT COUNT(*) FROM wallet w JOIN app_user u ON u.id = w.user_id WHERE u.role IN ('ADMIN', 'FRANCHISEE')` returns 0 on dev and staging.
- [ ] PR description names the affected user IDs and confirms the SQL was run on staging via `aws ssm send-command`.
- [ ] Existing webhook tests + a new test asserting the role-gate behaviour pass.

## Blocked by

Issue 01 (shared `INTERNAL_ROLES` module).
