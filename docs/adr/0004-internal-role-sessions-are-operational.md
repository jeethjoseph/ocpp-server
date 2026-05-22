# Internal-role charging sessions are purely operational

Charging sessions initiated by an ADMIN or FRANCHISEE user (`INTERNAL_ROLES`) are treated as purely operational events, regardless of funding source. They produce no `GSTInvoice`, debit no `Wallet`, and are not constrained by any `WalletSession` budget cap. The OCPP audit trail and `MeterValue` rows are recorded normally so ops can see how much energy was delivered. Internal-role users do not need a `Wallet` row.

The skip enforcement lives **inside the wallet services** (`WalletService.process_transaction_billing` and `WalletSessionService.cache_session_on_start`) — they early-return when the transaction's user has a role in `INTERNAL_ROLES`. Call sites stay role-agnostic. The role check uses the shared `INTERNAL_ROLES` set, promoted out of `services/invoice_service.py` into a top-level `core/roles.py` so it can be imported by webhook handlers and wallet services without crossing service boundaries oddly.

Status of an internal-role session at completion: `TransactionStatusEnum.COMPLETED`. An `audit_log` row is written with `action=transaction.status_changed`, `trigger=InternalRoleSkip`, and a reason naming the policy, so operators looking at the audit later can see why no `WalletTransaction` exists for the session. Metric counters `Custom/Wallet/InternalRoleSkipped` and `Custom/WalletSession/InternalRoleSkipped` fire alongside the existing `Custom/Invoice/InternalRoleSkipped`.

## Scope and the QR-funded edge case

The skip applies to *all* sessions initiated by an internal-role user, regardless of funding source. We assume internal users do not in practice scan QR codes or initiate UPI payments — those flows are customer-only. If that assumption ever changes, the rule narrows to "wallet-funded + admin-triggered only" so externally-collected money still produces a GST invoice for tax compliance. The working assumption is recorded in `CONTEXT.md` and should be reviewed if admins/franchisees start making QR payments.

## Considered alternatives

- **Wallet-funded only (the original assumption baked into `invoice_service.py:213-220`'s comment).** Rejected: simpler rule is fine given the working assumption above, and the existing comment "*These deduct from the initiator's wallet*" was already inaccurate the moment we added the wallet-billing skip — it's getting deleted anyway.
- **Enforcement at call sites instead of inside the services.** Rejected: rule lives in one place this way; every new caller of `process_transaction_billing` would otherwise have to remember to gate on role. The wallet services becoming "role-aware" is a small layering wart that's worth the single-point-of-policy benefit.
- **New `TransactionStatusEnum` value like `OPERATIONAL` or `INTERNAL_COMPLETE`.** Rejected: requires an enum migration and updates to every `transaction_status__in=[…]` query in the codebase. The current `COMPLETED + role-based query filter` is cheaper. If reporting needs grow, revisit.
- **Defensive cleanup migration deleting all internal-role wallets.** Rejected: too aggressive. Manually delete the 7 existing backfilled wallets via a one-shot SQL run instead; the gate at `webhooks.py` prevents new ones.
- **Refunding any QR payment that lands on an internal-role user.** Out of scope per the scope decision above. Defensive guard can be added later if needed.

## Consequences

- A future contributor reading `WalletService.process_transaction_billing` sees a `user.role` lookup and wonders why a wallet service is role-aware. The early-return + comment explains it; this ADR is the longer answer.
- The existing 7 backfilled wallets (data from the 2026-05-19 sanjana incident) are deleted as part of the change. Any future internal-role user gets no wallet at creation; a role-demotion to USER will lazily create a wallet via the existing `routers/wallet_payments.py:128` path on first top-up attempt.
- Energy delivered by internal-role sessions IS recorded in `MeterValue` rows and the OCPP audit trail, but is NOT reflected in any `WalletTransaction` or `GSTInvoice`. Ops dashboards counting "energy delivered" should join on `user.role` or sum from `MeterValue` directly when they want internal-vs-customer breakdowns.
