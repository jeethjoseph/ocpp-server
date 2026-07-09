# Stackable QR payments extend one session's budget (1:N), not multiple transactions

A same-payer QR payment made against an already-**CHARGING** charger **tops up the existing QR Session's budget** and charging continues with **no StopTransaction**. The physical session remains **one OCPP transaction / one `Transaction` row**; it is now funded by **N `QRPayment`s (1:N)**. A single **GST invoice** covers the delivered energy; the unused budget is refunded **LIFO** across the payments at stop. A **different** payer on a busy charger keeps today's behavior: reject + full-refund.

## Context

QR budget caps live in `qr_session:{transaction_id}` (Redis), enforced on MeterValues by a flag-less, at-least-once RemoteStop when `cost ≥ budget`. Today, a payment landing on a busy charger is **rejected and full-refunded** (`qr_payment_service.py` — "Concurrent payment rejected — charger busy"). Users who want to charge longer than their first payment allows have no way to extend without the session stopping.

The decisive constraint: the OCPP `transaction_id` handed to the charger **is** the app `Transaction.id` (`main.py` StartTransaction returns `transaction_id=transaction.id`). Every MeterValues and the StopTransaction carry that single id for the whole physical session. So "one continuous session" and "one id" are the same fact, welded by primary key.

The requested feature ("keep charging on a second payment; keep billing 1:1") cannot be literally satisfied: continuous charging ⇒ one id ⇒ one `Transaction`, but 1:1-with-stacking ⇒ many `Transaction`s. One had to give.

## Decision

**Model B — budget top-up, relax 1:1 → 1:N.** One `Transaction` per physical session; a same-payer top-up adds to `budget_limit_paise`; the existing cap machinery fires RemoteStop later.

- **Authorization to stack is same-payer only**, matched on `customer_vpa` with `customer_contact`/phone fallback. No match ⇒ unchanged reject + full-refund (protects a stranger who scans a busy charger from silently funding someone else's charge).
- **Top up unconditionally while CHARGING**; do not attempt to detect or cancel an in-flight RemoteStop (OCPP offers no reliable cancel). If a top-up races the stop, the added amount becomes unused budget and is refunded — self-healing, no special-casing.
- **Budget = Σ (amount_paid − synthetic_platform_fee)** across all linked CHARGING payments (synthetic fee per ADR 0001; per-payment, so fees compose).
- **One GST invoice per session** for total delivered energy — the taxable event is energy delivery, not payment.
- **LIFO refund** of the unused remainder at StopTransaction (most recent payment first).
- **No ceiling** on stack count or total budget.

## Considered alternatives

- **Model A — continuation transactions (preserve literal 1:1).** Finalize the current `Transaction`'s billing mid-session at the live meter reading and open a new `Transaction` per payment while the OCPP session runs on. Rejected: the charger keeps stamping the *original* id, so this requires an indirection layer (OCPP id → active billing segment) threaded through **every** OCPP handler that resolves a transaction from a message, plus a brand-new "bill on a MeterValues reading with no StopTransaction" trigger, plus multiple GST invoices carved by payment-arrival timing (a compliance smell — one continuous supply). High blast radius; breaks the glossary invariant that a Charging Session *is* one OCPP transaction. Its only real advantage — a separate invoice per payment — is a business requirement we do not have.
- **Pro-rata refund allocation.** Rejected: forces a partial refund on every payment (more Razorpay calls/fees, messier reconciliation) with no fairness benefit — it is one payer.
- **In-flight RemoteStop suppression** (race-detect and keep the session alive). Rejected: OCPP has no reliable cancel; buys concurrency bugs for a case the LIFO refund already absorbs.
- **Anyone-can-stack** (top up a busy charger regardless of payer). Rejected: a stranger's payment would fund someone else's charge and vanish. Same-payer matching keeps the existing safety net.
- **A stack ceiling** (max count / max budget). Rejected for v1: each top-up is a genuine same-payer prepayment; LIFO refund makes any excess whole. A cap only adds another reject branch.

## Consequences

- `QRPayment.transaction` becomes genuinely 1:N (the FK already permits it — no migration). Anything assuming "one QRPayment per Transaction" must be revisited.
- **Durability trap (must-fix):** `_load_or_rebuild_qr_session` currently rebuilds the budget from a single `.first()` CHARGING payment. It **must sum all CHARGING payments** for the transaction; otherwise a Redis blip mid-session collapses the budget to one payment's worth and fires a **spurious RemoteStop** on a paid-up customer. The DB is the durable source of truth for the *summed* budget; the top-up write sets Redis to the same running sum.
- Refunds stay per-payment (`qr_payment_{PK}` idempotency key unchanged); LIFO decides which payments refund and by how much. Existing zero-energy / fault-refund full-refund bands still apply and degenerate LIFO to "refund everything."
- The Charging Session glossary invariant (one session = one OCPP transaction) is **preserved** — a virtue of Model B over Model A.
- Everything at or after the session-end seam (transaction finalizing/finalized) is not "busy," so a later same-payer payment falls through to the normal new-session (RemoteStart) flow — no new code path.
