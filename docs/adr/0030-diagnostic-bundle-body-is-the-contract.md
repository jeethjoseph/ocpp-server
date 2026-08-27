# The Diagnostic Bundle body is the whole contract — the header is deleted, and the charger keeps no state across reboot

**Status:** accepted (2026-08-27) — supersedes the **bundle header**, **epoch**, and **loss accounting** portions of [ADR 0029](0029-diagnostic-bundle-authenticated-https-upload.md). Everything else in ADR 0029 stands unchanged: the HTTPS transport, the **Charger Auth Key** Basic Auth from [ADR 0020](0020-charger-websocket-basic-auth.md), the S3 archive, the durability gate, server-side redaction, rate limiting, upload cadence, and the OTLP fan-out.

ADR 0029 put a fixed header on every Diagnostic Bundle — `boot`, `seq`, `first`, `last`, `overflow` — and derived loss from it. Every one of those fields requires the charger to persist a counter across reboot. The firmware team has confirmed it cannot, and eight days in the field confirmed it independently: not one of the five fields has ever been correct. This ADR deletes the header. The **body is the only contract**, and everything the server needs is an **in-band record** the firmware already emits.

## Context

The header design assumed durable, monotonic, cross-reboot counters in the charger's EEPROM. Two things broke that.

**The firmware cannot provide them.** The EEPROM holds the ring buffer, and ADR 0029's own §3.2 argument explains why a persisted counter is hostile to this part: a pointer at a fixed address takes every write and the M24M02 is rated 1.2 million cycles at 85 °C — roughly two weeks at one record per second, silently, in the field, after warranty. A monotonic counter has exactly that write pattern. "We can't persist a counter" turns out to be the same constraint that motivated wear levelling, not an oversight.

**The field data agrees.** From the staging test unit (`8fc4b8a2-…`) on 2026-08-27, across the 15 bundles indexed before ingest wedged:

- `boot` ran `54, 56, 58` — skipping 55 and 57 — then reset to `1`.
- `seq` stayed at `4` across four bundles covering four *different* record windows, violating §4.1's "incremented per upload that produces a new bundle".
- `overflow` was emitted as a **negative** value packed into a uint32: rejected values decode as `-1`, `-191`, `-18100`, `-19148`. The magnitudes match `first_record - 1` exactly, so the firmware emits one quantity with inconsistent sign.
- Because a repeated `seq` reads as a reflash, the server-assigned `epoch` incremented on almost every upload, reaching 11 in 15 bundles. Both loss functions bail when the epoch changes, so **19,165 records the charger explicitly reported destroying were recorded as `0`**.
- The columns were `INT` (int32) against a `uint32` wire format, so `overflow = 0xFFFFFFFF` raised `invalid input for query argument $8: 4294967295 (value out of int32 range)`. Ingest returned 500 on every upload for hours, and because the S3 write precedes the index write, each retry stranded another object: 92 objects against 15 rows.

A loss-detection system whose failure mode is *"reports zero loss"* is the wrong way round, and this one reached that state through five independent defects in a single mechanism.

**The header is also the sole source of spurious variance.** Three consecutive retries of one logical bundle, identical in size, produced three different SHA-256 digests. Diffing them:

```
#VLTDIAG/1 boot=55 seq=2 first=15207 last=15381 overflow=0
#VLTDIAG/1 boot=55 seq=2 first=15207 last=15433 overflow=0
                                          ^^^^^ only difference
body lines differing: 0 of 460
```

The bodies are byte-identical. Only the header moved. The field that exists to identify a bundle is the one field that makes identical bundles look different.

**Meanwhile, the body already carries what the header claimed to.** From real bundles in `voltlync-diagnostics-staging`:

| Marker | Present | Evidence |
|---|---|---|
| Reboot boundary | yes | `===== BOOT @278 ms, reset reason 3 =====` — 3 in one 196 KB bundle |
| Absolute clock anchor | yes | `TIME_SYNC boot_ms=375751 utc=2026-08-27T09:16:37Z src=Heartbeat drift=+17 ms` — 36 in the same bundle, median 20 s apart |
| Boot counter | yes | `I (714) DIAGBUN: boot count = 1` |
| Ring-wrap event | yes | `DiagUpload: body short by 80 B (ring wrapped mid-upload) — padding` |

`services/diagnostic_fanout.py` already parses the first two and its docstring explains why per-segment anchoring is mandatory ("two anchors in one real bundle disagreed by 73 seconds"). The parsing exists and is correct. It runs on the **derived view** and not on the path that does the accounting, which trusts a header summary of what the body already says, in a form requiring persistence that does not exist.

## Decision

**Delete the header.** `#VLTDIAG/1 boot= seq= first= last= overflow=` is removed from the firmware contract. A bundle is a body: newline-delimited UTF-8 records, nothing else.

**Everything the server needs is an in-band record.** The unifying rule: if the server needs to know something, the firmware **logs it as a record**, never as persisted state. A record survives in the ring buffer without a dedicated EEPROM write, and it is self-describing when it arrives.

**Identity is `SHA-256` of the raw received body, excluding a leading `#VLTDIAG/` line.** Unique per charger, replacing `(charger_id, epoch, bundle_seq)`.

Two details are load-bearing rather than incidental:

- **Excluding the legacy header line is required from day one**, not after the firmware stops sending it. The evidence above shows the header is the only thing that varies between retries; hashing it in means nothing ever dedupes, and the mechanism silently fails against real traffic while passing synthetic tests.
- **Hash the raw received body, not the redacted one.** Identity answers "has this charger sent me these bytes before", which must be stable against our own policy. Hashing post-redaction means adding one redaction pattern rotates every historical digest and makes every old retry look new.

This needs no firmware state, and cannot be confused by a reused sequence number — the defect currently in the field.

**`epoch` is deleted outright.** It existed only to stop a reflashed unit's `seq=1` colliding with a historical `seq=1`. With no sequence there is no collision, no epoch, and no epoch-inflation bug silently zeroing the loss metrics.

**Reboot segmentation reads the `===== BOOT` marker**, and clock anchoring reads the per-segment `TIME_SYNC` line — logic already in the fan-out, lifted into a shared parser used by both ingest and fan-out. A counter that resets on reboot *is itself* a reboot detector; we never needed a persisted boot number, only the ability to tell reboots apart, and the marker does it better because it also carries the reset reason.

**Anchoring must resolve retroactively within a boot.** `boot_ms` is monotonic for the life of a boot, so a single `TIME_SYNC` fixes the wall-clock time of **every** record in that boot, including records written before the sync occurred. This is what makes the mechanism survive an outage: a charger that loses network logs unanchored, reconnects, emits `TIME_SYNC`, and the whole preceding segment becomes resolvable. Implementations must anchor in both directions from the sync point, not forward only.

**Loss accounting moves from record numbers to a UTC time window.** Each bundle records `first_utc` and `last_utc` resolved from its anchors. A hole between one bundle's `last_utc` and the next bundle's `first_utc` is a candidate loss window, alertable above a configurable threshold.

**Cumulative overwrite accounting is not achievable, and this ADR does not replace it.** ADR 0029's sharpest idea was that a gap and an overflow have opposite remedies and must be told apart. That distinction required a monotonic counter in storage separate from the data it describes. Without cross-reboot persistence there is no such counter, and **no in-band record recovers it** — the firmware's `ring wrapped mid-upload` line is a *recency* signal ("wrapping is happening now"), not a running total, and under sustained loss earlier wrap records are themselves overwritten by later ones. We keep the recency signal because it is free and genuinely useful. We do not claim it substitutes for the counter. Anyone reading this looking for "how many records did we lose in total" should know the answer is no longer available at any price the hardware supports.

**The upload response gets trimmed.** The charger logs our HTTP response into the ring buffer, which is then uploaded, producing a response that is logged again:

```
I (44694) EC200U: |ecord_count":2346,"header":{"boot":1,"seq":1,...},
                   "body_preview":"#VLTDIAG/1 boot=1 seq=1 first=589 last=1612 overflow=1\n..."
```

`body_preview` echoes 200 characters of the bundle just uploaded straight back into the buffer it came from. At ~700 bytes per response this is a self-feeding consumer of the exact resource the feature exists to conserve. The response is cut to a minimal ack.

**Archive and index become atomic.** The S3 write currently precedes the row insert with no compensation, so any index failure strands an object the retention sweep can never reclaim — it only deletes objects it has rows for. The two are made to succeed or fail together, index-first, because compensating the other way needs an `s3:DeleteObject` grant that ADR 0029 deliberately withholds.

**Schema change is expand/contract, not a single drop.** The superseded columns stop being written and become nullable first; they are dropped in a later, separate migration once the UTC window has been observed against real traffic. Dropping immediately would destroy the historical values with no way back if the replacement underperforms, and re-adding a column carries the Aerich snapshot risk this repo has been bitten by before. One extra migration buys a rollback.

## Consequences

**Firmware changes: none required.** Every marker this design depends on is already in shipped bundles. The firmware team's only work is *removing* the header. That inverts the previous position, where the header imposed persistence requirements the hardware could not meet.

**Gap resolution drops from records to minutes.** Record numbers made silence unambiguous; timestamps do not distinguish "nothing was logged" from "records were lost" below the anchor cadence.

**Cumulative overwrite accounting is gone** — see the Decision. This is the largest single capability lost, and it is lost to the hardware constraint rather than to this design.

**The clock anchor depends on the network.** All observed `TIME_SYNC` records come from `src=Heartbeat` (33) or `src=BootNotification` (3); there is no RTC or local time source. Retroactive within-boot anchoring means a transient outage resolves fully once the charger reconnects. The residual failure is narrow but real: a boot that **never** achieves network is entirely unanchorable, and modem registration failure is one of the conditions this feature exists to diagnose. Such bundles fall back to server receipt time as a coarse upper bound so they still land on a timeline.

**First relief for a wedged charger comes only when the header parsing is removed.** The identity and loss-window work does not stop a 500 loop. If an outage needs ending quickly, removing the header parse is the short path and can be taken alone.

**About half of `diagnostic_bundle_service.py` is deleted** — `_resolve_epoch`, `_is_same_bundle`, `_overflow_delta`, `_gap_records`. The module keeps its purpose ("did we receive everything?") and loses the machinery that could not answer it.

## Considered alternatives

**Widen the columns to BigInt and keep the header.** The immediate unblock, rejected as the *design*: it fixes only the crash, leaving the reused `seq`, the epoch inflation, the negative overflow and the persistence requirement untouched.

**Require the firmware to persist counters properly.** Rejected on the hardware argument the original ADR itself makes, and it asks the firmware team to solve a wear-levelling problem to supply information already in the body.

**Server-assigned sequence numbers.** Detects nothing — a bundle that never arrives is never numbered, so the gap it leaves is invisible, which is the failure the header existed to catch.

**Record-level dedupe instead of bundle-level.** Merging overlapping record streams makes retries, reflashes and reboots all non-issues, and is the logical endpoint of this direction. Deferred, not rejected: it needs a record-level index the ingest path does not have today. Content hashing gets the safety now at a fraction of the cost.

> **Update 2026-08-27 — Q1 answered, and it lands better than feared.** The charger persists **only its identity and configuration** (charger ID, server endpoint, auth key). No counters, no markers, no pointers survive a reboot — the (b) case, not the (a) this ADR assumed.
>
> The first read of that was that the charger, unable to know what it had sent, would re-send overlapping windows after every restart and defeat bundle-level hashing. **That overstates it.** The charger *overwrites records it has already delivered*, reclaiming their space eagerly, so the buffer trends toward holding only undelivered records. A post-reboot re-send is therefore mostly **correct behaviour** — genuinely undelivered data — rather than duplication.
>
> Residual overlap is real but bounded: a reboot landing shortly after a successful upload, before the freed space has been reused, leaves just-delivered records still physically present to be re-sent. At most one buffer window, and only in that timing. Bundle-level content hashing plus the loss window is adequate; record-level dedupe stays deferred.
>
> **This does sharpen the durability gate.** A 2xx does not merely let the charger advance a marker — it actively frees those records to be overwritten. A false 2xx is immediately destructive rather than eventually so, which is exactly the hazard `archived_at` closes: an unarchived reservation must never answer a retry as delivered.

## Still open

- ~~Is loss accounting still a goal at all?~~ **Decided 2026-08-27: yes, keep it.** The UTC-window replacement is built. It is understood to be approximate — resolution in minutes, no cumulative overwrite count, and dependent on a network-sourced clock anchor. The alternative (drop to archive-and-search) was considered and rejected: a coarse loss signal is still worth more than none, given silent loss was the original justification for the whole feature.
- **Does a format version survive?** ADR 0029 deliberately made the first header byte a version marker, and deleting the header deletes the only negotiation point for a future format change. A single `#VLTDIAG/2` line would keep it, at the cost of contradicting "the header is deleted".
- **The gap threshold's empirical basis.** The 300 s starting value derives from one unit during *active* OCPP traffic (median 20 s, max 212 s). Heartbeat interval is per-charger configurable and an idle unit may be far quieter, so the sample is from the wrong operating state as well as being small.
- Whether the firmware adds a volatile `DIAGBUN: overflow=<n>` record for within-boot exactness, or whether the existing wrap line is signal enough.
- **Bounded post-reboot overlap.** Because the charger reclaims delivered space eagerly, a restart mostly re-sends genuinely undelivered records. The exception is a reboot landing before freed space has been reused, which re-sends records we already hold under a different digest. Whether that warrants a per-charger high-water mark on `last_utc` applied to the fan-out — keeping the search index clean while S3 keeps every copy — should be decided from real reboot data, not guessed at now. Not urgent.
