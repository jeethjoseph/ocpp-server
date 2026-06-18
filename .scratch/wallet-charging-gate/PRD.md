# Temporarily gate wallet charging behind a flag

## Problem

Franchisee settlement uses Razorpay Route, where every transfer is tied to an
original `payment_id`. This works for **QR Sessions** (one UPI payment → one
split) but not for **Wallet Sessions**: a single pooled top-up funds many
sessions across many franchisees with no per-session source `payment_id`.
Settling those requires Razorpay Direct Transfer (`POST /v1/transfers`) plus a
pooled-money → multi-franchisee reconciliation ledger that **does not exist
yet**. Today, wallet sessions on franchisee chargers park in `ON_HOLD`
(`wallet_settlement_not_activated`) and can never be settled.

Rather than accrue open-ended unsettleable franchisee liability, we pause wallet
charging and route all customers through QR until the ledger + Direct Transfer
are built.

Full rationale and re-enable gate: **ADR 0011**
(`docs/adr/0011-wallet-charging-gated-until-pooled-settlement.md`).

## Goal

Introduce a single flag `WALLET_CHARGING_ENABLED` (default `true`; set `false` on
staging/prod) that prevents **new** wallet sessions and top-ups, while leaving
everything else — wallet billing, balance reads, in-flight sessions, and all QR
flows — fully operational.

## Scope (blast radius — exactly three things)

1. Hide the wallet UI (top-up modal + "start with wallet").
2. 403 the two remote-start endpoints (`remote_start_charging`,
   `remote_start_by_string_id`).
3. 403 the wallet top-up order endpoint.

**The backend flag is the source of truth.** The frontend flag is cosmetic — a
stale frontend build is still safe because the endpoints reject. RFID
local-start is not used, so gating the remote-start endpoints is sufficient; no
StartTransaction backstop is needed.

## Explicitly out of scope (stays ON)

- Wallet billing at StopTransaction, budget-cap auto-stop, GST invoicing.
- Wallet balance reads (admin wallet pages).
- Existing wallet balances — **frozen, not refunded**; resume on re-enable.
- Wallet sessions already running at flip time — complete and settle normally.
- All QR flows (scanner, QR payment, QR settlement).
- The pooled-settlement ledger and Razorpay Direct Transfer work — that is the
  *re-enable* prerequisite, tracked separately, not part of this feature.

## Non-negotiable constraints

- Default `WALLET_CHARGING_ENABLED=true` so dev/existing envs are unaffected;
  only staging/prod set `false`.
- Backend var must reach the container: add to `backend.environment:` in **all
  three** compose files, not just `.env.example` (CLAUDE.md env-var trap).
- Frontend `NEXT_PUBLIC_` var must have `ARG`+`ENV` in `frontend/Dockerfile` and
  `build.args:` in staging/prod compose, or it bakes empty (CLAUDE.md frontend
  build-arg trap).

## Issues

- `01-backend-flag-and-endpoint-guards.md` — safety-critical enforcement slice
- `02-frontend-wallet-ui-gate.md` — cosmetic UI hide
- `03-enable-on-staging-prod-and-verify.md` — config rollout + verification
