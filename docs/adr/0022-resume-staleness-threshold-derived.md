# The resume-staleness threshold is derived from the disconnect window, not configured independently

The staleness guard that refuses to resume a long-suspended transaction (`transaction_finalizer.is_resume_too_stale`) must take its threshold from the **same computed cutoff the stale-suspended sweeps use** — `disconnect_handler.stale_suspended_cutoff_seconds()` = `max(DISCONNECT_SUSPEND_TIMEOUT, SUSPEND_TIMEOUT) + buffer` — instead of from an independent `MAX_RESUME_GAP_SECONDS` env var. Deriving it makes the guard **structurally guaranteed** to be a backstop that fires *after* the primary disconnect timer, so the ordering can never be misconfigured, and a charger that reconnects inside its legitimate reconnect window always resumes.

## Context — three overlapping finalizers and one fragile invariant

A `SUSPENDED` charging transaction (charger dropped its OCPP WebSocket mid-session) can be force-finalized by **three** different mechanisms, each with its own threshold:

1. **`DISCONNECT_SUSPEND_TIMEOUT_SECONDS`** (default 180s, **1800s in prod/staging**) — the **primary, proactive** timer. `disconnect_handler._disconnect_suspend_timeout` is an in-memory `asyncio` task scheduled the moment the charger disconnects; if the txn is still `SUSPENDED` when it fires, it finalizes `DISCONNECT_TIMEOUT`. This is the real policy knob: *how long we hold a disconnected session open for a reconnect.*
2. **`MAX_RESUME_GAP_SECONDS`** (default 900s) — the **staleness guard**, `is_resume_too_stale`, checked **reactively at resume time** (BootNotification, MeterValues, and the `GetLastMeterValue` DataTransfer). If the gap since last activity exceeds it, the resume is refused and the txn finalized `STALE_RECONNECT`. Its documented purpose (`transaction_finalizer.py:35-41`) is *defense-in-depth for when the primary timer chain has failed* — e.g. a process restart that loses the in-memory `asyncio` task.
3. **The stale-suspended sweep** — `finalize_stale_suspended_transactions`, cutoff `stale_suspended_cutoff_seconds()` = `max(DISCONNECT_SUSPEND_TIMEOUT, SUSPEND_TIMEOUT) + 60` (=1860s in prod). Runs at startup and on every billing-retry cycle; finalizes `SUSPENDED_TIMEOUT`. Also a backstop for the lost-timer case.

For the design to hold, the guard (2) must fire **strictly later** than the primary (1): the invariant `MAX_RESUME_GAP_SECONDS > DISCONNECT_SUSPEND_TIMEOUT_SECONDS > SUSPEND_TIMEOUT_SECONDS`. Because `MAX_RESUME_GAP_SECONDS` is a **separate, hand-set env var**, nothing structurally enforces this — it is a comment-documented convention an operator can silently break.

### It was broken, and it cost real sessions

Prod and staging ran `MAX_RESUME_GAP_SECONDS=900` while `DISCONNECT_SUSPEND_TIMEOUT_SECONDS=1800` — inverted (`900 < 1800`). The "backstop" became the **primary killer**, refusing legitimate resumes in the 15–30 min band that the disconnect timer was still granting:

- **Txn 870** (QR session, charger VOW0008, 2026-06-04): WS dropped at full 7.34 kW after 0.366 kWh. Charger reconnected at **18m12s** (`gap_seconds=1092`) — well inside the 30-min disconnect window — but the 15-min staleness guard refused the resume (`transaction.resume_blocked`, `STALE_RECONNECT`) and finalized on the stale pre-disconnect reading, refunding ₹17.09 of ₹27.50. The session **should have resumed.**

This is the same class of failure as the sweep-cutoff drift already fixed in `.scratch/suspend-sweep-threshold-fix/` issues 01/02 (2026-06-18, prompted by txn 949, force-stopped at 8m45s by a billing-retry sweep still using the 5-min cutoff). That work **consolidated the two sweeps** into one shared helper with a **computed** cutoff precisely so two independently-maintained thresholds could never drift apart again. The staleness guard is the one finalizer that was **left out of that consolidation** — still an independent number that can be misordered below the primary timer.

### The guard is nearly redundant in practice

With the invariant satisfied, order the three by when they fire in prod: primary **1800s** → sweep **1860s** → guard **2100s** (the value both envs were raised to on 2026-06-09). The sweep beats the guard to nearly every lost-timer case by 240s, so the guard almost never fires on its own. Its only unique contribution is refusing a resume in the narrow window where the primary timer *and* a sweep cycle are both missed and a charger reconnects. It is the most redundant of the three finalizers **and** the one that caused the outage.

## Decision

Retire `MAX_RESUME_GAP_SECONDS` as an independently-configured value. `is_resume_too_stale` derives its threshold from `disconnect_handler.stale_suspended_cutoff_seconds()` — the **single source of truth** already shared by both sweeps:

```
resume_staleness_threshold = stale_suspended_cutoff_seconds()
                           = max(DISCONNECT_SUSPEND_TIMEOUT, SUSPEND_TIMEOUT) + BUFFER
```

Consequences of deriving rather than configuring:

- The invariant `guard ≥ primary` is **structurally guaranteed** — the guard is `max(primary, …) + buffer`, so it can never fire before the primary timer regardless of how the two timer envs are set. The misordering that killed txn 870 becomes **unrepresentable**, not merely "documented".
- The guard settles into exactly its intended role: a resume-time fast-path for the sweep's job, sharing the sweep's cutoff so all three finalizers agree by construction.
- One fewer operational knob. `MAX_RESUME_GAP_SECONDS` is removed from `.env*.example`, the three `docker-compose*.yml` `backend.environment:` blocks, and the code default. The two timer envs (`DISCONNECT_SUSPEND_TIMEOUT_SECONDS`, `SUSPEND_TIMEOUT_SECONDS`) remain the only tunables; the reconnect grace window is set in exactly one place.
- The `BUFFER` (60s) is shared with the sweep, so the guard and sweep remain within 0s of each other by definition — whichever observes the stale txn first finalizes it, and the outcome is identical (`finalize_stopped_transaction`, terminal-state guarded).

This is a **behavior-preserving change for correctly-configured environments** (prod/staging already run 2100 ≈ the derived 1860): it removes a failure mode, it does not change the happy path.

**Scope boundary.** This ADR addresses only *when a resume is refused* — the ordering/redundancy of the finalizers. It does **not** address the deeper defect that finalize-on-timeout bills and refunds against the last meter reading seen before the disconnect, with no reconciliation against the energy the charger delivered during the outage (the money leak that survives even a permitted-but-late finalize, and the push-only `PostBootState`/`GetLastMeterValue` handshake). That reconciliation decision is tracked separately and is the higher-value fix; deriving the threshold narrows *exposure* to it by ensuring every in-window reconnect resumes, but does not remove it.

## Considered alternatives

- **Add a startup `validate_timing_invariants()` that refuses to boot on `MAX_RESUME_GAP ≤ DISCONNECT_SUSPEND`.** This is the fix proposed in the resume-gap incident memory. Rejected as the *primary* fix (kept as a complementary idea): it **detects** a bad combo instead of making it **impossible**, still exposes an independent knob, and a boot-time guard that only some deploys hit is weaker than a value that cannot be wrong. Deriving subsumes it for this specific invariant. A boot-time validator over the *remaining* independent knobs (`DISCONNECT_SUSPEND ≥ SUSPEND`) is cheap and can still be added, but is out of scope here.
- **Just keep `MAX_RESUME_GAP_SECONDS=2100` and move on.** This is the 2026-06-09 hotfix and is what unblocked prod. Rejected as the *durable* answer: it makes the invariant *true today* but leaves it *fragile* — one `.env` edit (or a compose default falling through to the code default of 900 on a deploy that forgets the override) reintroduces txn 870. The value is correct; the *design* that lets it be wrong is the bug.
- **Remove the staleness guard entirely and rely on the primary timer + sweep.** Defensible — the sweep already beats the guard by 240s, so deleting the guard loses only the resume-time fast-path. Rejected (for now) as more surgery than needed: the guard is cheap, and once its threshold is derived it is harmless and provides marginally faster finalization of a zombie reconnect. Deriving is the minimal change that fixes the actual defect; outright removal can be revisited if the guard proves to earn nothing.
- **Fold the guard into the sweep consolidation as a fourth caller of a shared "is this txn past its window" predicate.** Effectively what deriving the threshold achieves at the value level; a full structural merge (guard calls the exact sweep predicate) is a reasonable follow-up refactor but not required to close the invariant hole.

## Consequences

- **Txn 870's failure mode cannot recur** — an 18-minute reconnect is below the derived cutoff, so it resumes. Post-fix `STALE_RECONNECT` finalizes should stay at zero for in-window reconnects.
- A contributor tuning the reconnect window now edits **one** value (`DISCONNECT_SUSPEND_TIMEOUT_SECONDS`) and the guard + both sweeps track it automatically. There is no second number to keep in order.
- The env-var checklist in `CLAUDE.md` shrinks by one var; `.env*.example` drift on `MAX_RESUME_GAP_SECONDS` (flagged still-open in the resume-gap memory) is resolved by deletion rather than reconciliation.
- Regression coverage: a test asserting that a disconnect-suspended txn reconnecting at `DISCONNECT_SUSPEND_TIMEOUT + small` resumes (not `STALE_RECONNECT`), and that one reconnecting past the derived cutoff is refused — locking the ordering at the `is_resume_too_stale` seam. Existing suites `test_resume_staleness_guard`, `test_disconnect_resume_integration`, `test_disconnect_handler`, `test_billing_retry_stale_suspended` must stay green.
- Relationship to prior work: this completes the direction of `.scratch/suspend-sweep-threshold-fix/` (one source of truth for the stale-suspended cutoff) by bringing the third finalizer under the same computed threshold. See also ADR 0010 for the "derive/​bound, don't leave a knob that hangs the system" pattern applied to DB pool timeouts.

## Verification — the energy-during-blackout leak is disproven fleet-wide (2026-07-06)

The original bug report claimed the charger "continues delivering full energy" through a WS disconnect, producing a free charge. A cumulative-odometer sweep over **every disconnect-finalized session in prod history** (11 sessions across 6 chargers spanning both 3.3 kW and 7.4 kW units) tested this directly: compare the meter reading at the last pre-disconnect frame against the `start_meter_kwh` of the next session on the same charger.

**Result: 8 flat (±0.1 kWh), 3 reboot-resets (negative), 0 advanced.** No charger's odometer moved during a blackout — every unit opens the contactor and stops delivering on WS loss. The screenshot incident (txn 870, VOW0008) is the reference case: meter frozen at 0.366 kWh from 10:12:55 through the 18-min outage and the next session's start at 10:32:22.

Consequences for this ADR's scope boundary:

- The **money-leak mechanism does not occur** on any deployed charger. Every disconnect-finalize refund observed was **correct** (customers refunded for energy they genuinely didn't receive). The reconciliation/"refund-on-stale-reading" concern deferred above is therefore **latent, not active** — it would only bite a future firmware that keeps the contactor closed on WS loss, which none currently does. This makes deriving the staleness threshold (below) the **whole** fix for the observed harm, not merely a partial one.
- The **actual, confirmed harm** is what this ADR targets: an in-window reconnect (870 at 18 min) force-finalized instead of resumed, fragmenting one charge into two separately-paid QR sessions (txn 870 refunded + txn 871, distinct `razorpay_payment_id`, same customer, 65 s later) and forcing a second payment. Deriving the threshold so 870 resumes eliminates exactly this.
- Two secondary findings surfaced during verification, out of scope here but worth tickets: prod backend **log retention is ~1.3 days** (too short for OCPP-frame forensics on older incidents), and the `transaction.finalized` **audit event was missing** for txn 870 (a fire-and-forget `safe_create_task` that didn't persist — the `transaction` row was still correct).

### Complementary gap — StartTransaction does not reconcile an existing open transaction

The double-payment fragmentation has **two** enablers; this ADR closes only the first:

1. **The resume path refuses an in-window reconnect** — fixed here by deriving the staleness threshold.
2. **`StartTransaction` (`main.py:754-857`) creates a new transaction unconditionally** — it validates charger/user/active but has **no check for an existing `RUNNING`/`SUSPENDED` transaction** on the charger. So a charger that reconnects and sends a *fresh* StartTransaction (instead of resuming) spawns a second transaction alongside the still-`SUSPENDED` orphan, which is later swept — reproducing the pay-twice harm without going through the resume path at all.

Deriving the threshold (this ADR) does not close enabler 2. Its design is decided (2026-07-06) and tracked separately in `.scratch/ws-disconnect-refund-rca/issues/04`: **reconcile-then-accept, scoped per `connector_id`** — on StartTransaction, finalize any stale/`SUSPENDED` transaction on that connector via the canonical finalizer, then accept the new session; reject with OCPP `ConcurrentTx` *only* for a genuinely-live same-connector transaction (a recent MeterValue). A blanket fail was rejected: the charger emitting StartTransaction is authoritative that a new session is beginning, so rejecting strands a paying customer and — on firmware that ignores a non-`Accepted` response — risks untracked, unbilled charging. Sequence this ADR first (smaller, higher-confidence); the StartTransaction reconcile is the follow-up that fully closes the fragmentation.
