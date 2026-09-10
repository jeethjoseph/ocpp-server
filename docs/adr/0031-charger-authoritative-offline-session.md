# The charger is authoritative for an in-flight session; the CSMS holds, then writes off

Firmware will **hold the contactor closed and keep delivering through a CSMS outage** instead of opening it on WebSocket loss. That single change moves the authority for an in-flight session to the charger, and the CSMS follows it: the per-session **Budget cap** is pushed to and enforced *at* the charger, a suspended session is held on **silence** rather than session age, the queued-and-replayed `MeterValues` stream becomes the sole billing input, and a session that stays silent past its window is finalized against server-available data with the unreported energy **written off** rather than chased. `PostBootState` and `GetLastMeterValue` — both of which exist only because the charger could not previously remember its own meter — are retired.

Status: **decided 2026-09-09, not yet built.** Firmware and CSMS changes ship together; neither half is safe alone.

## Context

### What changes physically

Today a charger opens its contactor when the OCPP WebSocket drops. Charging stops, the car sits idle, and when the link returns the session either resumes or is force-finalized. The customer's charge is hostage to a cellular modem on a fleet where, per ADR 0027, 41% of reconnects arrive via BootNotification and site power events routinely take three chargers down together.

The new behaviour: connectivity loss alone never opens the contactor and never triggers a reset. Local safety supervision — earth fault, leakage, over/under voltage, over-current — is untouched and continues to stop the charge through its existing paths; those are local decisions that never consulted the CSMS. The only thing suppressed is a reset whose sole cause is that the CSMS is unreachable.

### The finding this deliberately inverts

ADR 0022 carries a fleet-wide verification (2026-07-06) over **every** disconnect-finalized session in prod history — 11 sessions, 6 chargers, both 3.3 kW and 7.4 kW units — comparing the last pre-disconnect reading against the next session's `start_meter_kwh`:

> **Result: 8 flat (±0.1 kWh), 3 reboot-resets (negative), 0 advanced.** No charger's odometer moved during a blackout — every unit opens the contactor and stops delivering on WS loss.

On that basis the refund-on-stale-reading leak was recorded as **latent, not active**, with an explicit precondition:

> it would only bite **a future firmware that keeps the contactor closed on WS loss, which none currently does.**

This is that firmware. The leak becomes live on the day it ships, and every consumer of `SUSPENDED` has to be re-read on the assumption that the charger may be delivering energy right now. That is the central fact of this ADR: we are knowingly activating a deferred failure mode because the thing it buys — a customer's overnight charge surviving a power cut — is worth more than the energy we will lose to it.

### Why the budget must move to the charger

A charger that keeps delivering while unreachable and has **no local energy limit** delivers unbounded free energy. The local cap is therefore not a peer feature of offline continuity; it is its **precondition**. Neither ships without the other.

OCPP 1.6 has no native per-transaction energy limit. `SetChargingProfile` constrains power over a time schedule, not cumulative energy — converting one to the other requires predicting the AC taper curve, which is exactly what cannot be done reliably. `MaxEnergyOnInvalidId` is a Charge-Point-wide constant that applies only after an idTag is invalidated mid-session. The gap is real and the OCA closed it natively only in 2.1. So a vendor `DataTransfer` is the correct and idiomatic 1.6 answer — that is what the extension point exists for.

### Why the queue is the billing input, and what it does not need to hold

OCPP 1.6 requires **transaction-related** messages (`StartTransaction`, `StopTransaction`, and `MeterValues` carrying a `transactionId`) to be queued while offline and delivered **in chronological order**; retries are governed by the standard `TransactionMessageAttempts` and `TransactionMessageRetryInterval` configuration keys. Non-transaction-related messages (`StatusNotification`, `Heartbeat`) may be dropped or coalesced.

A replayed frame is therefore not degraded data — it is the same frame with the same timestamp, delivered late. An early draft of this decision treated replayed data as inherently less trustworthy than live data and proposed a server-side physics-plausibility gate. That reasoning does not survive contact with the spec and was dropped.

It also follows that the metering store does **not** need to hold every frame to bill correctly. `Energy.Active.Import.Register` is a cumulative absolute odometer and every billing path reads it as one (`energy_consumed_kwh = end_meter_kwh − start_meter_kwh`; the budget check does `reading_kwh − start_meter`). Losing intermediate frames to a ring wrap costs **granularity, not energy**. The metering partition must protect the odometer and whatever frame density we want for audit and live display — not 17,280 frames per 48-hour session.

### What the meter does on a reboot, and why that is the only real failure mode

The one way a chronologically-perfect replay still produces a wrong bill:

```
t+0h    meterStart = 11,000 Wh
t+3h    reading    = 14,200 Wh     (queued, correct)
        ── site power cut; charger reboots; register resets ──
t+9h    reading    =    900 Wh     (queued, in order, cumulative-nonsense)
t+9h    meterStop  =    900 Wh
```

`energy_consumed_kwh = 0.9 − 11.0 = −10.1 kWh`. Nothing is out of order; the sequence is simply wrong. This is not hypothetical — it is the **3 reboot-resets** in the sweep above, and a power cut is precisely the event that produces a mid-transaction reset *and* takes the link down, together, routinely.

A reset cannot be scheduled away. A *deliberate* reset (commissioning, meter swap) can be constrained to "no open transaction"; an *involuntary* one is what happens when the meter chip loses power, and firmware gets no vote on the timing. The achievable invariant is stated one level up, about the wire rather than the hardware: **the charger never reports a cumulative reading lower than one it has already reported for the same transaction.** The register may reset; the firmware must reconstruct before reporting.

This is what makes retiring `PostBootState` a coupled decision rather than a cleanup. Per the firmware HLD, `PostBootState` was *how* a charger recovered its meter baseline after a reboot — "the meter sync has not happened… the live reading would be the raw hardware counter, not the synced value." Removing it leaves charger-side EEPROM persistence as the **sole** remaining recovery mechanism, with no fallback and — per `docs/known-issues.md` — no credit note to correct an invoice issued on a bad figure.

## Decision

1. **Offline continuity.** Connectivity loss never opens the contactor and never triggers a reset. Local safety paths are unchanged and still stop the charge. Retry cadence uses the standard `TransactionMessageAttempts` / `TransactionMessageRetryInterval` keys, settable per-charger via `ChangeConfiguration`, rather than a firmware-hardcoded schedule.

2. **The Budget cap is enforced at the charger, which is the source of truth.** Pushed as an absolute Wh value in a vendor `DataTransfer` (`messageId=SessionLimit`), keyed on **`transactionId`** and sent immediately after `StartTransaction.conf`. The Wh conversion **rounds down**. The message carries an absolute value, is idempotent, and is **re-sendable** — re-asserted on every reconnect and re-pushed whenever the budget changes. The server-side `check_budget_and_auto_stop` is **retained as a redundant failsafe**, not retired: whichever enforcer fires first wins, on the same flag-less at-least-once basis already used for auto-stop dispatch.

   Keying on `idTag` was rejected: `rfid_card_id` is a per-`User` value minted once at user creation and reused across every session that customer ever has, so it cannot identify a session — and the ambiguity is worse against a limit persisted in EEPROM across reboots.

3. **A suspended session is held on silence, not session age.** The clock measures time since we last heard anything about *that transaction*; a charger checking in with advancing energy resets it. There is consequently **no upper bound on session duration**, which is correct — advancing energy is proof of life. The window governs only the no-information case. ADR 0027's `latching` split **survives** — it remains the right discriminator when we know nothing, since a latched cable means the car is probably still attached — with magnitudes raised (~48h latched; the unlatched value is raised but stays materially shorter, and is **still to be set**). `suspended_at` is the wrong column to measure from and is replaced.

4. **Past the window, finalize on server-available data and write off the difference.** The unreported energy is never billed and never refunded against. This is a deliberate, accepted loss; the alternative is stranding a customer's money indefinitely on hardware that may never return.

5. **A late `StopTransaction` records the truth without moving the money.** `on_stop_transaction` gains the terminal-state guard it currently lacks: it must not overwrite billed fields on an already-finalized transaction. The charger's reported figures are written to separate reported-only fields with an audit event and an alertable NR event. The billed figures — and the GST Invoice already issued against them — are left untouched.

6. **`PostBootState` and `GetLastMeterValue` are retired together.** Both exist only because the charger could not remember its own meter. Retirement is gated on fleet firmware rollout, because today's firmware genuinely depends on the `PostBootState` push. `GetLastMeterValue` currently also **resumes** a session (`SUSPENDED → RUNNING`, incrementing `resume_count`); that side effect must be guaranteed by the `MeterValues` replay path, which already auto-resumes.

7. **The charger owns the meter; the CSMS observes but does not correct.** No clamping, no server-side adjustment — the meter is the instrument of record. A monotonicity violation within a transaction is logged as an alertable event **and billed as reported**. Observation is not overruling: with the `PostBootState` fallback gone and no credit-note mechanism, this is the only signal that charger-side meter persistence has failed in the field.

8. **`MeterValue` may store the OCPP frame timestamp — optional, not blocking.** Currently the frame's `timestamp` is parsed, debug-logged and discarded; only `created_at` (server receipt time) is stored.

   An earlier draft made this a hard prerequisite on the grounds that a replay would blind `is_resume_too_stale` and make the meter-baseline lookups undefined. **Both arguments fail on inspection.** Decision 3 measures *silence* — time since we last heard about the transaction — so receipt time is the semantically correct field, and a replay legitimately resets it. And `auto_now_add` stamps each row at its own save with microsecond resolution, so sequential inserts of an in-order replay order correctly under `created_at`. Billing needs only the cumulative start and end. Forensics is already covered: `core/connection_manager.py` persists every inbound frame verbatim into `log.payload`, timestamp included, for the 90-day `RETENTION_DAYS` window.

   What remains is a **query-convenience denormalization** with one real argument — the retention asymmetry between `log` (90 days) and `meter_value` (indefinite) — plus robustness if a charger ever drains its queue out of order, which decision 7's monotonicity observation would catch anyway. Cheap, useful, not a blocker.

   **SHIPPED (migration 62).** Built on that basis: cheap, useful, not load-bearing.
   - `MeterValue.measured_at`, `Transaction.reported_start_time`, `Transaction.reported_end_time` — all nullable, all additive. `start_time` / `end_time` keep their meaning as **server receipt** and remain the billing and GST-invoice basis; the reported values sit beside them, per decision 5's record-don't-overwrite rule. `reported_end_time` is the only record of when a charge actually stopped when a `StopTransaction` arrives hours late.
   - `utils.parse_ocpp_timestamp()` is the single parser, with a **clock plausibility guard**. This is not defensive padding: charger clocks in this fleet are known-unreliable, which is why ADR 0030 reconstructs Bundle time from in-band `TIME_SYNC` anchors rather than believing the charger. A reported time is accepted only within `OCPP_CLOCK_SKEW_SECONDS` (300s) of the future and, where the caller knows one, no earlier than a floor — the transaction's `start_time` for MeterValues and StopTransaction. Outside that: **NULL plus a warning**, never a silent substitution of receipt time, so a bad clock degrades to prior behaviour instead of poisoning the record. It also replaces the one hand-rolled `fromisoformat` in the StatusNotification handler.
   - `services/meter_readings.py` owns the read side, and the six meter-baseline call sites (post-boot push, resume DataTransfer, failed-txn energy, finalizer, QR budget snapshot, admin backfill) share it so they cannot drift. **The two readers order differently, deliberately.** `latest_meter_value()` — the billing baseline — orders by **receipt** (`created_at`, `id`). `meter_series()` — the delivery curve — orders by **measured** time, `COALESCE(measured_at, created_at)`. Note Tortoise's own `Coalesce()` takes a **literal** as its fallback — both a bare string and `F("created_at")` are passed to asyncpg as a query parameter and rejected — so the series uses `RawSQL` over fixed column names.

     **Why the baseline is receipt order (corrected 2026-09-10 after review).** The first cut ordered the baseline by measured time too, and it regressed. The clock guard deliberately admits a charger running up to 300 s fast; a frame stamped +4 min, then an NTP correction, then a later frame stamped +1 min put the earlier, *lower* reading on top. Reproduced on the dev DB — A id=321 at 1.0 kWh measured +4m, B id=322 at 9.0 kWh measured +1m, `latest_meter_value` returned A — and every affected caller is one that bills without a charger-supplied stop reading, so the finalizer would have under-billed a 9 kWh session as 1 kWh. Receipt order is monotonic by construction, which is the one property a billing baseline cannot do without. And because OCPP 1.6 requires chronological delivery, the two orderings agree whenever the charger behaves; where they differ, receipt order is the one that cannot go backwards. The retained timestamp keeps the job it was actually kept for — the delivery curve and forensics — which is the basis on which this decision was downgraded to *optional* in the first place. A per-transaction relative floor in the parser was considered and rejected: it needs a query per `MeterValues` frame on a table with no index for that ordering, the wrong trade on a 10-second-cadence path. A backwards *reading*, as opposed to a backwards clock, is decision 7's concern.
   - **`is_resume_too_stale` deliberately still reads `created_at`**, with a comment saying why: it measures *silence*, a receipt-time question, and a charger replaying an hours-old queue has just proved it is alive. Ordering that by `measured_at` would resurrect a stale gap and refuse a live resume — the txn 870 failure, reintroduced by a well-meaning cleanup.
   - Chart/export series ordering (`routers/users.py`, `franchisee_portal.py`, `transactions.py`) is **left on `created_at`** for now. Measured time is more correct there too, but those feed CSV exports under the IST column conventions in CLAUDE.md, and changing exported data is a separate, compliance-adjacent decision.
   - **`measured_at` is deliberately NOT indexed.** A first cut added one and it was useless: reads order by `COALESCE(measured_at, created_at)`, and a btree index on `measured_at` alone cannot serve that expression. Verified on a 20k-row probe with `enable_seqscan=off`, where the planner still chose a full scan plus top-N heapsort rather than use it. An index there would have cost write amplification on the highest-write table in the system — one row per MeterValues frame per charger — and returned nothing. Every reader narrows by `transaction_id` first (served by the FK index) and none sit on a per-frame path: the per-frame QR budget check passes `reading_kwh` explicitly and never reaches the lookup. If profiling ever disagrees, the index that would actually work is `(transaction_id, COALESCE(measured_at, created_at) DESC, id DESC)`. Migration 62 is therefore three plain `ADD COLUMN`s — no index build, no deploy lock.
   - 21 new tests in `test_reported_ocpp_timestamps.py`; 171 green across the twelve affected suites.

9. **Offline session *start* stays disabled.** `AllowOfflineTxForUnknownId` and `LocalAuthorizeOffline` are set `false` explicitly via `ChangeConfiguration` rather than trusting vendor defaults, and asserted at commissioning. Every session requires a funding decision only the CSMS can make. Continuity is about surviving an outage mid-session, never about beginning one during it.

10. **Metering state is protected from diagnostic buffering — but it is small.** ADR 0030 accepts ring-wrap as normal for **Diagnostic Bundles**: correct for disposable observability data, unacceptable for billing data, and by that ADR's own design nothing can report how much was lost. So diagnostics must never be able to overwrite metering state, keeping the separation CONTEXT.md draws where a Bundle is "strictly non-metering… that exclusion is what keeps a Bundle disposable observability data rather than legal-metrology data adjacent to a GST Invoice."

    **Scope correction.** This was originally sized at 138–276 KB, from a table of 17,280 queued frames per 48-hour session, and framed as a serious contention against the ~238 KB Diagnostic Bundle ring. That sizing was wrong, because it assumed billing needs the full frame series. It does not: the register is a cumulative odometer, so **billing needs the odometer, the last reading, and `StopTransaction`** — a few hundred bytes. Losing intermediate frames to a wrap costs granularity, not energy. The requirement on firmware is therefore *"the odometer and last reading survive, and diagnostics cannot scribble on them"*, not *"carve up the EEPROM"*. Frame density above that floor is an audit and live-display choice, freely traded against diagnostic depth.

11. **`SUSPENDED` occupies its charger.** Shipped ahead of the rest, since it was a live hole: `OPEN_TRANSACTION_STATES` (`models.py`) is now shared by the StartTransaction reconcile guard and the QR double-payment guard, so they cannot drift. `SUSPENDED` is included — under continuity it is the state a genuinely-charging session sits in, and treating it as free let a second payment open a parallel session on physically busy hardware. `PENDING_STOP` stays excluded: superseding a txn mid-normal-stop races the StopTransaction path into a double-finalize, and per ADR 0021 the session-end seam is not "busy".

### Why not just migrate to OCPP 2.x instead

Most of this design is a hand-rolled 2.x. The mapping is close to one-to-one:

| Built here | Native construct | Version |
|---|---|---|
| `PostBootState` push | Unnecessary — the station assigns `transactionId` and owns its meter | 2.0.1 |
| `GetLastMeterValue` pull | Same — the question stops existing | 2.0.1 |
| Silence clock / inferring what we missed | `seqNo` per `TransactionEvent` | 2.0.1 |
| Inferring which frames were generated offline | `offline` flag on the event | 2.0.1 |
| Inferring `SUSPENDED` means "probably still charging" | `chargingState` reported explicitly | 2.0.1 |
| `SUPERSEDED_BY_NEW_START` inference | `TransactionEvent(Ended)` + `stoppedReason` | 2.0.1 |
| `SessionLimit` `DataTransfer` | `TransactionLimit` (maxEnergy/maxCost/maxTime/maxSoC) | **2.1 only** |

Note too that ADR 0021's decisive constraint — the OCPP `transaction_id` *is* the app `Transaction.id`, "welded by primary key" — is a **1.6 artefact**. Under 2.0.1 the station assigns the id, and the indirection that forced Model B over Model A stops being a problem.

**Deferred anyway, on one decisive argument: 2.0.1 does not solve the headline problem.** `TransactionLimit` is 2.1, and the installed `ocpp==2.0.0` library exposes `v16` and `v201` only. We would complete the migration and still ship `SessionLimit` as a vendor `DataTransfer` — the most bespoke piece survives. Add that 2.0.1 on ESP32-S3 means the full device model (Components/Variables, `GetVariables`/`SetVariables`) and new security profiles — a larger firmware lift than the continuity work itself — and it would block a customer-facing fix behind a protocol migration. Server-side cost is near zero (`ocpp.v201` is already installed), firmware cost is not.

**Position: stay lean on 1.6 now, migrate to 2.0.1 later.** The window stays cheap — the fleet is 22 connectors, per ADR 0027. Migration shims (`seqNo`, an `offline` flag, a `TransactionLimit`-shaped payload) were considered and **rejected as overhead** for a win that did not justify them; the one zero-cost item, naming the `SessionLimit` fields `maxEnergy`/`maxCost`/`maxTime`, is optional.

### The constraint underneath all of this

Decisions 2, 4 and most of 5 exist because **we take the money before we know the energy.** That is a payments constraint, not a protocol one: postpaid with pre-auth and capture-actual deletes the local cap, the write-off and the reconciliation outright. UPI offers no practical hold/capture primitive for a walk-up flow in India today (Autopay mandates are too heavyweight), so the constraint is real — but it is worth recording as a payments limitation rather than an assumption, because if it ever lifts, a large part of this design becomes deletable rather than migratable.

## Accepted trade-offs

- **Energy delivered during a blackout that never reaches us is lost revenue.** Bounded per session by the prepaid **Budget cap**, and only on sessions that stay silent past the window.
- **A GST Invoice may under-state delivered energy**, permanently. There is no credit-note table (dropped in migration 27) and stamping a correction breaks the register invariant. Decision 5 keeps the register internally consistent — an invoice that matches its transaction's billed figures — at the cost of a documented gap against reported figures. A register that silently disagreed with its own transactions was judged strictly worse.
- **No upper bound on session duration** while a charger keeps reporting progress. ADR 0027 already flagged a 36h flap ceiling as a concern; this removes the ceiling. Deliberate — killing a session we can see is alive was never the intent.
- **QR money can be held ~48h** on a silent latched session before any refund. ADR 0027 accepted 12h on the same reasoning; this extends it.
- **A stacked top-up landing while the charger is unreachable cannot be honoured.** The charger stops on the limit it holds and ADR 0021's LIFO refund returns the top-up in full — self-healing, but the customer paid to keep charging and did not. Costs nothing today: ADR 0021 is **accepted but unbuilt** (no stacking code exists). When stacking is built it must be designed against a charger-authoritative limit from the start, not retrofitted.
- **Two enforcers can both fire.** Accepted as the existing at-least-once pattern; duplicate RemoteStops are idempotent at the charger.
- **A vendor `DataTransfer` is not interoperable.** A future non-VoltLync charger will not understand `SessionLimit`. Unavoidable in 1.6 and the reason to prefer 2.1 when the fleet allows.

## Considered alternatives

- **Keep force-finalizing on the existing windows.** Status quo. Rejected: it closes the books irreversibly on a session that is still running, issuing an uncorrectable invoice against a stale reading.
- **Finalize provisionally and reconcile the delta later.** Rejected: requires rebuilding the credit-note machinery migration 27 removed, and touches issued GST invoices — the largest new surface of any option, for a loss we can bound instead.
- **Hold indefinitely with no deadline.** Rejected: a scrapped or permanently-dead charger would strand a customer's money forever with no refund path.
- **Raise the existing windows and change nothing else.** Rejected: moves the cliff without removing it.
- **Charger limit as a backstop sitting above the server's, with headroom.** Would preserve ADR 0021's stacking behaviour exactly and keep the well-tested online path primary. Rejected in favour of a single source of truth: one enforcer that behaves identically online and offline, at the cost of a stacking regression that is currently theoretical.
- **Server-side physics-plausibility gate on replayed frames** (clamp to `max_power_kw × elapsed`). Rejected: rested on the incorrect premise that replayed data is less trustworthy than live data, and second-guesses the instrument of record. Replaced by the narrower monotonicity observation in decision 7.
- **Invert `PostBootState` for capable firmware, keep the push for legacy.** Rejected in favour of outright retirement: maintaining two reconnect protocols indefinitely costs more than sequencing one removal behind the firmware rollout.
- **Reuse `ACTIVE_TXN_STATES` for the busy guard** (decision 11). Rejected: it includes `PENDING_STOP`, which would have regressed both the double-finalize race and ADR 0021's session-end-seam rule.

## Consequences

- `SUSPENDED` no longer implies "not delivering energy". Every consumer of that state must be re-read — the customer-facing `PAUSED` sub-state in `qr_session_state.py` now describes a car that may be actively charging, and the `/api/users/active-session` surface ADR 0027 added inherits the same problem.
- The `SUPERSEDED_BY_NEW_START` inference from RCA issue 04 is weakened: it was correct *because* the old firmware stopped delivering, so a stale orphan really was dead. A charger's direct report that a transaction is still live must override it.
- `_get_charger_last_meter_wh()` derives its push from the previous transaction's `end_meter_kwh`, which after a write-off is exactly the stale figure. It dies with `PostBootState`.
- The firmware requirement for `last_energy_wh` must specify **torn-write durability**: rotate the write across the live-state slots, checksum each record, and on boot take the newest slot that validates. The failure mode is a power cut landing mid-write — the exact event the value exists to outlive.
- Regression coverage must include: a replay whose register resets mid-transaction; a late `StopTransaction` against a written-off session leaving billed fields and the invoice untouched; a `SessionLimit` re-asserted on reconnect; and a session held open indefinitely while energy advances.
- Follow-ups not settled here: the unlatched suspend-window value; whether the customer app should distinguish "paused" from "charging offline"; migrating `SessionLimit` to native OCPP 2.1 transaction limits when the fleet allows.
