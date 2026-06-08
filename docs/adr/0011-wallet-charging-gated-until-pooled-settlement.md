# Wallet charging gated off until pooled multi-franchisee settlement exists

Status: accepted

The entire **Wallet** implementation is intact and working, but **wallet charging is
deliberately switched off** behind the `WALLET_CHARGING_ENABLED` flag (default
`true`; set `false` on staging/prod) until the pooled-money → multi-franchisee
settlement ledger is built. If you are tempted to "just turn wallet back on
because the code clearly works" — stop and read this first.

## Why

Franchisee settlement uses Razorpay Route, and **every Route transfer is tied to
an original `payment_id`**. This maps cleanly for a **QR Session**: one UPI
payment → one transfer split on that payment. It does **not** map for a **Wallet
Session**:

- A single **Wallet** top-up (one Razorpay `payment_id`, e.g. ₹1000) funds *many*
  charging sessions across *potentially many different franchisees*.
- The per-session franchisee payout therefore has **no source `payment_id`** to
  split against. It requires Razorpay's standalone Direct Transfer
  (`POST /v1/transfers`) **plus** a reconciliation ledger that tracks which slice
  of which pooled top-up was paid out to which franchisee.
- That pooled-prepaid → fan-out ledger **does not exist yet.** Until it does, a
  wallet session on a franchisee charger produces a `CommissionLedgerEntry` that
  parks in `ON_HOLD` with `wallet_settlement_not_activated` and can never be
  settled (see `services/franchisee_settlement_service.py`).

Rather than accrue an open-ended pile of unsettleable franchisee liability, we
pause wallet charging and route all customers through QR (which settles
correctly), until the ledger and Direct Transfer are in place.

## Decision / blast radius

`WALLET_CHARGING_ENABLED` gates exactly three things — nothing else:

1. **Frontend** (`NEXT_PUBLIC_WALLET_CHARGING_ENABLED`, build-time, cosmetic):
   hides the top-up modal and the "start with wallet" path so users don't hit
   dead ends.
2. **Backend remote-start endpoints** (`remote_start_charging`,
   `remote_start_by_string_id`): return 403 when off. **This is the real
   enforcement** — the backend flag is the source of truth, read at runtime via
   `os.getenv`, so a stale frontend build is still safe (worst case: a clean
   403).
3. **Wallet top-up order endpoint** (`wallet_payments` router): returns 403 when
   off.

The gate applies only to wallet-funded **customer** sessions. **Internal-role
(ADMIN/FRANCHISEE) sessions are exempt** — they are operational and decoupled
from wallets (ADR 0004), so `remote_start_charging` skips the 403 when
`user.role in INTERNAL_ROLES`. Admins/franchisees can still start sessions while
the gate is off.

Everything downstream stays on: wallet billing at StopTransaction, budget-cap
auto-stop, balance reads, admin wallet pages, and **all** QR flows. Wallet
sessions already running at flip time complete and settle normally (a small,
bounded `ON_HOLD` backlog). Existing wallet balances are **frozen, not refunded**
— they become spendable again on re-enable.

This is a blanket disable, not per-charger. A surgical version (allow wallet only
where `resolve_franchisee` is `None`, i.e. VoltLync-owned chargers) was rejected
as not worth the complexity for a temporary measure.

RFID local-start is not used in the fleet, so all wallet sessions originate from
the two remote-start endpoints; gating those is sufficient. No StartTransaction
backstop is needed. **If local RFID start is ever enabled, this guarantee breaks**
— add the StartTransaction funding-decision check at that point.

## Re-enable gate (in order)

Settle the backlog before re-opening the tap, so we never accrue unsettleable
sessions again:

1. Build the pooled-prepaid → multi-franchisee fan-out settlement ledger.
2. Activate Razorpay Direct Transfer (`POST /v1/transfers`) on the merchant
   account.
3. Set `WALLET_SETTLEMENT_ENABLED=true` → the existing retry sweep backfills the
   `ON_HOLD` backlog.
4. Set `WALLET_CHARGING_ENABLED=true` (backend restart re-opens the start path;
   frontend rebuild un-hides the UI; frozen balances become spendable).
