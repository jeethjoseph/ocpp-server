# StartTransaction should reconcile an existing open transaction (reconcile-then-accept, not fail)

Status: done

## What to build

`on_start_transaction` (`main.py:754-857`) validates charger + user + active status, then calls `Transaction.create(...)` **unconditionally** (`main.py:801`) — no check for an existing `RUNNING`/`SUSPENDED`/`PENDING_START` transaction on the same charger/connector. So a charger that reconnects after a modem drop and sends a **fresh StartTransaction** (instead of resuming) spawns a second transaction next to the still-`SUSPENDED` orphan, which is later swept. That fragments one charge into two separately-paid QR sessions (the txn 870/871 pay-twice pattern).

**Fix = reconcile-then-accept, scoped per `connector_id`:** on StartTransaction, if an open transaction already exists on the same connector:

1. **If it is `SUSPENDED` / stale** (the common case — an orphan from a disconnect): **finalize it** via the canonical `finalize_stopped_transaction(...)` so it bills/refunds correctly, then **ACCEPT** the new transaction. The new StartTransaction *is* the customer's real session — serve it.
2. **Only if it is genuinely, actively `RUNNING`** (a live MeterValue within the last ~N seconds, i.e. the charger is still reporting on it — anomalous on a single-connector unit): treat as a true concurrent case and **reject** with OCPP `idTagInfo.status = ConcurrentTx`.

## Why reconcile-then-accept, NOT a blanket fail

The obvious move is "reject StartTransaction if a transaction is already open." **Do not do that** — two OCPP-specific reasons:

- **The charger emitting StartTransaction is authoritative that a NEW session is beginning.** A charger only sends StartTransaction on a new plug-in/authorization. If our DB shows an open transaction but the charger is sending StartTransaction, the charger is right and our record is the stale one. The correct response is to close ours, not reject the charger.
- **Rejecting strands a paying customer and can create UNTRACKED charging.** The "existing open transaction" is almost always a `SUSPENDED` orphan from a modem drop. If a customer scans, pays (QR), plugs in, and we reject the StartTransaction because of that orphan, they **paid and can't charge**. Worse: OCPP 1.6 firmware is inconsistent about honoring a rejected StartTransaction — many units keep energizing on a non-`Accepted` response, producing a **physical session with no transaction record** (no billing, no budget cap, no meter storage). That is strictly worse than a duplicate transaction.

So a hard fail optimizes "protect our data model" at the cost of "customer paid and can't charge" + "possible unbilled energy." Reconcile-then-accept gets the same integrity win (one live txn per connector) without either downside. A hard reject is correct ONLY for a genuinely-live same-connector session — which on these single-connector, modem-flaky units is nearly always actually a stale orphan (the reconcile case).

## Open detail to settle in implementation

- **"Genuinely live" vs "stale" threshold:** classify the existing txn as live only if it has a MeterValue (or heartbeat) within the last ~N seconds; otherwise treat as stale and finalize. Pick N relative to the MeterValues cadence (frames land every ~10 s here, so ~60–90 s is safe).
- **Connector granularity:** guard on `connector_id`, not charger — current fleet is single-connector but don't bake that in.
- **Ordering vs the resume paths** (BootNotification / MeterValues / GetLastMeterValue): a StartTransaction that arrives *instead of* a resume must close the suspended session cleanly without double-finalizing — confirm the finalizer's terminal-state guard covers the race.
- **StartTransaction retries** (charger resends the same frame on a flaky link): dedupe so a retry doesn't itself trip the reconcile — key on connector + a short idempotency window.

## Acceptance criteria

- [ ] On StartTransaction, an existing `SUSPENDED`/stale transaction on the same connector is finalized via the canonical finalizer, and the new transaction is created and `Accepted`.
- [ ] A StartTransaction arriving while a prior txn is `SUSPENDED` on that connector never leaves two open transactions, and never rejects the new (paying) session.
- [ ] A genuinely-live same-connector transaction (recent MeterValue) yields `ConcurrentTx` and no second transaction.
- [ ] StartTransaction retries do not spuriously finalize the just-created transaction.
- [ ] Regression tests for all three cases; existing StartTransaction / disconnect-resume suites stay green.

## Blocked by

Pairs with issue 01 (ADR 0022). Sequence 01 first (smaller, higher-confidence); together they close both enablers of the pay-twice fragmentation — 01 stops the resume path from refusing an in-window reconnect, this stops the StartTransaction path from spawning a parallel session.

## Comments

Surfaced during the WS-disconnect RCA (2026-07-06). Design decided 2026-07-06: reconcile-then-accept, reject only on genuinely-live same-connector (was `needs-info` on the fail-vs-reconcile question). Rationale above — do not regress to a blanket fail.

**Implemented 2026-07-06.** Added module-level `_reconcile_existing_open_transaction(charge_point_id, charger, meter_start)` in `main.py` (module-level, not a ChargePoint method, so the mocked-self test harness exercises the real logic), called from `on_start_transaction` after the user-active check. Logic: find newest open txn on the charger; if RUNNING/STARTED with activity < `START_TXN_LIVE_WINDOW_SECONDS` (90s) → live: same meter baseline within `START_TXN_RETRY_WINDOW_SECONDS` (30s) returns the existing txn id (idempotent retry), else `ConcurrentTx`; otherwise (SUSPENDED, or stale RUNNING) finalize via the canonical finalizer with reason `SUPERSEDED_BY_NEW_START` and proceed. Constants are plain (no new env var). New tests in `test_start_transaction_reconcile.py` (5) cover all branches; 40/40 pass across the reconcile/finalizer/disconnect/resume suites and the existing `test_start_transaction_no_vehicle`. `test_integration.py`'s 5 setup-ERRORs are the documented pre-existing baseline flake (confirmed identical on a stashed clean tree), not a regression.

**Scope note:** scoped per CHARGER, not per connector — `Transaction` has no `connector_id` column, so per-connector needs a schema migration (out of scope; fleet is single-connector). A prominent code comment flags this for whoever adds multi-connector chargers.
