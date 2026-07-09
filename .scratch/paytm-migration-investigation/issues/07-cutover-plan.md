# 07 — Cutover plan [CONTINGENT PLACEHOLDER]

Status: ready-for-human

## What to build

**Contingent placeholder — do not start until the abstraction (06) exists.** The cutover strategy depends on the chosen decision (full-replace vs dual-rail) and the abstraction shape, so it is intentionally left thin.

Intended scope, to be detailed after 06:
- **Franchisee re-onboarding**: every franchisee currently has a Razorpay Route linked account; each needs a Paytm split-settlement vendor account created + KYC'd before their settlements can move. This is the dominant operational cost of cutover.
- **Dual-rail window**: how long both providers run in parallel, and how traffic is routed during it.
- **In-flight handling**: transactions, pending settlements, and open refunds that straddle the cutover.
- **Rollback**: how to fall back to Razorpay if Paytm misbehaves mid-cutover.
- **Shared-account hygiene**: avoid repeating the cross-environment collisions seen on the shared Razorpay live account.

## Acceptance criteria

- [ ] (To be defined after the abstraction is built — this issue must be re-sliced into concrete tracer bullets before work begins)

## Blocked by

- 06 — Payment-provider abstraction (design + build)
