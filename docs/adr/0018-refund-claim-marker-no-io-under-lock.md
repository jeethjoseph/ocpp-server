# Refund execution uses a claim-marker — no remote I/O held under the row lock

Status: proposed

QR refund execution must not hold a database row lock (and its pooled
connection) across the Razorpay HTTP call. Both refund paths acquire
`SELECT FOR UPDATE` on the `qr_payment` row inside `in_transaction()` and then
`await razorpay_service.refund_payment(...)` **while still holding the lock**.
The decision is to split each refund into three phases — **claim → call →
persist** — so the lock is held only for two fast DB transactions and never
across the network call. A new `REFUND_IN_PROGRESS` status marks the claim, and
the billing-retry sweep recovers any claim stranded by a crash.

## Context

Two functions execute refunds, and both wrap the Razorpay call in the lock:

- `QRPaymentService._full_refund` (`qr_payment_service.py`) — full refund for
  the ~10 "service not rendered" paths (zero-energy, fault, stale webhook,
  charger-not-connected, RemoteStart failure, plug-in timeout, concurrent
  rejection, charging failure, orphan cleanup). All ~10 call sites funnel
  through this one function, so the change is contained to it.
- `QRPaymentService._finalize_qr_billing` → `_issue_unused_credit_refund`
  (post-2026-06 hardening) — partial unused-credit refund after a billable
  session. Reachable concurrently from StopTransaction (`main.py`), the
  transaction finalizer, and the orphan sweep.

The hold:

```python
async with in_transaction():                     # txn open, pool connection borrowed
    locked = await QRPayment.select_for_update()  # row lock acquired
    ...
    await razorpay_service.refund_payment(...)     # httpx, timeout=10s  ← lock + conn held
    await locked.save()                            # commit releases lock + conn
```

While Python `await`s httpx, **no SQL is in flight**, so neither
`command_timeout` (30s) nor `statement_timeout` aborts the connection — it sits
*idle-in-transaction* for up to the httpx `timeout=10`. The asyncpg pool is
`maxsize=10` (`DB_POOL_MAX_SIZE`). Under a Razorpay latency spike with enough
concurrent refunds (across both paths), all 10 connections can be pinned waiting
on HTTP, after which **unrelated** requests fail on `DB_CONNECT_TIMEOUT=10s`. A
payment-provider slowdown becomes a site-wide DB-starvation incident.

**The enabling invariant:** the lock during the network call was only ever
protecting two things — (A) single payout and (B) single DB state-write. (A) is
**already** guaranteed independently by the Razorpay idempotency key
`refund_{razorpay_payment_id}` (globally unique; same key + body → one payout,
HTTP 200 replay). So the lock is genuinely needed only for (B), which is fast.
The network call never needed the lock; it held it only because "do it all in
one transaction" is the simplest shape.

**Honest tradeoff (why this is not a free win).** Because today's call is
*inside* the transaction, a crash mid-call **rolls the DB back** to the
pre-refund status; the next finalize/sweep re-issues with the same idempotency
key and reconciles to `REFUNDED`. Recovery is automatic. Splitting the
transaction introduces a new *stranded* state — claimed, but the call's outcome
unknown — that is **not** auto-recovered by rollback and must be swept
explicitly. We are trading "remote I/O under a lock" for "an intermediate state
with an explicit recovery obligation." The trade is worth it because the
starvation failure mode is operationally severe and the recovery path is a small
extension of the sweep that already re-issues idempotently.

## Decision

Restructure both refund executors into three phases:

```
T1 (claim)   ─lock─►  re-check not already claimed/refunded; persist refund_amount
                       (+ billing breakdown for the billable path) + the intended
                       post-refund terminal status; set status = REFUND_IN_PROGRESS;
                       commit; RELEASE lock.                         [fast, no network]

call         ──────►  razorpay_service.refund_payment(idempotency_key=...)
                       holding NO lock and NO open transaction — connection returned
                       to the pool during the HTTP wait.            [slow, unlocked]

T2 (persist) ─lock─►  re-lock; write razorpay_refund_id + the recorded terminal
                       status (REFUNDED, or EXPIRED preserved); on exception defer to
                       the existing _classify_refund_exception (REFUND_FAILED / reconcile);
                       commit.                                       [fast, no network]
```

Post-commit cache-invalidation + audit stay outside the lock (already the case
after the 2026-06 fix).

**New status `REFUND_IN_PROGRESS`** on `QRPaymentStatusEnum` (Aerich migration —
`CharEnumField`, additive, no backfill). It means "we have decided to refund and
committed the amount, but the Razorpay outcome is not yet confirmed."

**Recorded terminal intent.** `_full_refund` callers pre-set a terminal status
(`EXPIRED` for orphan/stale; the refund path otherwise lands `REFUNDED`).
`_perform_full_refund` today does `if status != EXPIRED: REFUNDED`. Because T1
overwrites status with `REFUND_IN_PROGRESS`, the *intended* post-refund terminal
status must be carried across the gap — store it on the claim (simplest: a
nullable `refund_terminal_status` column, or reuse the pre-claim status captured
in T1) so T2 restores `EXPIRED` vs `REFUNDED` correctly.

**Sweep recovery (the critical new obligation).** `BillingRetryService` gains a
branch: select `status = REFUND_IN_PROGRESS` rows older than a short threshold
(claimed but unconfirmed — a crash between T1 and T2), and run the **call → T2**
phases against them. Safe by the same idempotency key — Razorpay either creates
the refund (T1's call never landed) or returns the existing one (it did), and
`_classify_refund_exception` already reconciles `AlreadyRefunded`. The existing
`REFUND_FAILED`-retry branch is unchanged.

**State machine:**

```
CHARGING/PAID ──T1──► REFUND_IN_PROGRESS ──call+T2──► REFUNDED
   (or a                                   └─fail──►  REFUND_FAILED ──sweep──► REFUNDED
   _full_refund                            └─crash─►  (stranded) ──sweep──► REFUNDED
   precursor                  EXPIRED preserved through the cycle when set by the caller
   status)
```

The `refund.processed` / `refund.failed` webhook is unaffected: it keys on
`razorpay_refund_id` (only set at T2), stamps `refund_processed_at` + final
speed, and never drives `status` — so it composes cleanly with the new flow.

## Considered options

- **Claim-marker (chosen).** Removes remote I/O from under the lock entirely;
  keeps single-payout (idempotency key) and single-claim (T1 lock) guarantees;
  crashes become resumable via the sweep. Cost: one new status + migration, a
  terminal-status carry, a sweep branch, and a "refund processing" UI state.
  Contained to 2 functions + the sweep (call sites untouched).
- **Concurrency cap / refund semaphore (recommended as an immediate, independent
  mitigation).** Bound the number of in-flight refunds (e.g. an `asyncio.Semaphore`
  sized well under `maxsize`, or a dedicated small connection budget) so refunds
  can never pin the whole pool. Does **not** remove I/O-under-lock, but directly
  caps the starvation blast radius for a fraction of the effort and risk. Pairs
  with the claim-marker (ship first, as a safety net) or stands alone if we defer
  the structural change. Rejected as the *sole* fix because the lock-hold pathology
  remains; accepted as a complementary first step.
- **Drop the lock, rely only on the idempotency key (rejected).** Reintroduces
  the bug the 2026-06 lock fixed: two racers double-write state / audit / Redis
  (the key protects the payout, not the rows). Without a claim marker there is no
  single-claim guarantee.
- **Band-aids: raise `maxsize`, lower httpx timeout (rejected as primary).** Move
  the cliff without removing it; worth tuning regardless but not a fix.
- **Status quo / accept (rejected).** The risk is bounded (10s) and mirrors the
  already-shipped `_full_refund` pattern, but it is a real under-load resilience
  hole on the customer money path; leaving it undocumented is the worst option.

## Consequences

Good: a Razorpay slowdown can no longer starve the DB pool; the row lock is held
only for sub-millisecond transactions; refunds become crash-resumable with
structured recovery; single-payout and single-claim invariants are preserved.

Costs / risks: a new intermediate state customers/admins may observe ("refund
processing") — UI and the GST/ops views must render it as not-yet-terminal; the
sweep gains crash-recovery responsibility (the riskiest new code — must be tested
against a simulated crash-after-claim); a migration adds the enum value; the
terminal-status carry must be correct so `EXPIRED` orphan/stale refunds don't get
flipped to `REFUNDED`. Because this is the customer money path, it ships behind
tests-first (see the implementation plan) and ideally after the cheap semaphore
mitigation is already live.

Relates to: ADR 0001 (synthetic vs actual fee — refund math unchanged), ADR 0002
(instant-refund speed — `speed`/reconcile semantics unchanged), and the 2026-06
refund-classifier + row-lock hardening this supersedes for the lock-hold concern.
