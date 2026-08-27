# Diagnostic Bundle — Required Changes (v1.2)

**Date**: 2026-08-27
**Audience**: Firmware team
**Based on**: staging uploads 2026-08-19 → 2026-08-27, including the 196 KB full-size bundle and the first authenticated uploads
**Amends**: [Required Changes v1.1](./diagnostic-bundle-required-changes-v1.1.md) and [Firmware Specification v1.0](./diagnostic-bundle-upload-spec.md)
**Background**: [ADR 0030](../adr/0030-diagnostic-bundle-body-is-the-contract.md)

## The short version

**We are deleting the bundle header, and withdrawing every requirement that asked you to keep a counter across a reboot.**

You told us the hardware can't hold those reliably. The staging data agreed — `boot` skipped values and reset, `seq` stopped incrementing, and `overflow` went negative. Rather than ask you to solve that, we rebuilt our side to read what it needs from records **you already emit**.

Net effect: **three requirements withdrawn, one line deleted, nothing new to build.** Two live items from v1.1 remain outstanding.

---

## Status of the v1.1 checklist

| ID | Item | Status |
|---|---|---|
| C1 | `TIME_SYNC boot_ms=… utc=…` per boot segment | ✅ **done** — shipped and verified. Now load-bearing; see C1′ below. |
| C2a | Overflow counter increments on wraps during read-out | ❌ **withdrawn** — no header, no counter |
| C2b | Stop padding short bodies; header must agree | ⚠️ **partly withdrawn** — see C2′ |
| C3 | `Meter E` totalizer redacted | ❌ **still outstanding** — see C3′ |
| C4 | Confirm `first` / `last` semantics | ❌ **withdrawn** — no header, question moot |
| C5a | ~192 KB upload attempted | ✅ **done** — 196,588 B uploaded 2026-08-21, body intact |
| C5b | Upload during an active charging session | ⏳ still open |

---

## What already works — please don't regress it

Everything from v1.1's list still holds, plus:

- **Authentication works.** The Charger Auth Key over HTTP Basic authenticated correctly on the first attempt once the URL was right. We verified the presented key against our stored hash — exact match.
- **Full-size uploads work.** 196,588 bytes over HTTPS, body byte-intact. That closes C5a.
- **`TIME_SYNC` is shipping and correct.** 36 of them in one 196 KB bundle, median 20 s apart:
  ```
  I (376185) CLOCK: TIME_SYNC boot_ms=375751 utc=2026-08-27T09:16:37Z src=Heartbeat drift=+17 ms
  ```
- **BOOT markers are shipping and correct.** Three in the same bundle.
- **Ring-wrap events are logged in band.** `DiagUpload: body short by 80 B (ring wrapped mid-upload) — padding`

These four are now the **entire** mechanism for reconstructing time and detecting loss. Treat them as contractual.

---

## C1′ — `TIME_SYNC` is now load-bearing, not merely helpful

No change needed. Context so nobody removes it as noise.

Because `boot_ms` is monotonic within a boot, one `TIME_SYNC` dates **every** record in that segment — including records written *before* the sync arrived. That is what makes an outage recoverable: log unanchored while the modem is down, emit `TIME_SYNC` on reconnect, and the whole preceding segment becomes readable.

Verified on your 196 KB bundle: our resolved window starts at **06:06:41.899**, which is *before* that bundle's own first anchor at 06:06:53.

Two asks, both "keep doing what you're doing":

- **One anchor per boot segment minimum**, more is better.
- **Never anchor across a BOOT marker** — that is our job and we do it per-segment. Your two anchors in the v1.1 bundle disagreed by 73 s precisely because they belonged to different boots.

## C2′ — Padding: no longer a correctness problem, still wasted bytes

C2b asked you to stop padding short bodies because the header had to agree with what was sent. There is no header now, so the correctness argument is gone and **this is no longer a blocker**.

It is still worth fixing when convenient: we observed repeated 32,848-byte bodies where the real content was smaller, so the padding is uploaded over cellular and archived for 90 days. Purely a cost item now.

The `ring wrapped mid-upload` line that accompanies it is **promoted** — it is now our only in-band signal that the buffer is destroying undelivered records. Please keep emitting it with a stable prefix so we can match it reliably.

## C3′ — Metering totalizer redaction (still outstanding, now escalated)

Unchanged from v1.1 C3 and still happening. We are redacting **28 cumulative energy values in a 33 KB bundle, and 157 in a 196 KB one** — it scales with bundle size:

```
I (23744) ATM90E26: [AVERAGED] V: 269.47 V | I: 0.00 A | ... | Meter E: 0.00000 kWh
```

Firmware reports `redacted: 0 meter` while these are plainly in the body, so the firmware-side matcher is not catching them.

Our server-side redaction is a second line of defence, not a substitute. This is the item with compliance weight: energy reaches the CSMS through the audited `MeterValues` / `StopTransaction` path, and a second unaudited copy becomes a liability the moment the two disagree.

**Keep** V, I, PF, Freq — device health, no billing meaning. It is specifically `Meter E` that must not appear.

---

## C6 — Delete the header line (new)

Remove this from the top of every bundle:

```
#VLTDIAG/1 boot=17 seq=42 first=100234 last=102301 overflow=0
```

The body now starts with the first log record.

**This is not a flag-day.** We will keep accepting bundles that still carry the line — it is treated as an ordinary log record and ignored. Ship it whenever it suits you.

## C7 — Stop logging our HTTP response into the ring buffer (new)

The charger is writing our upload response into its own log buffer. We know because it comes back to us on the next upload:

```
I (44694) EC200U: |ecord_count":2346,"header":{"boot":1,"seq":1,...},
                   "body_preview":"#VLTDIAG/1 boot=1 seq=1 first=589 last=1612 overflow=1\n..."
```

That is our JSON response — including a preview of the bundle you just sent — written back into the buffer that bundle came from, then uploaded again next cycle. It consumes the exact resource the feature exists to conserve, and it recurs indefinitely.

We have cut our side already: the response is now ~120 bytes and carries no preview (see below). It should not be logged at all.

## C8 — Optional: a volatile overflow count

Only if it is cheap. A **since-boot, not persisted** count of records overwritten before delivery, emitted as an ordinary record:

```
I (12345) DIAGBUN: overflow=75 since boot
```

Resets to zero every boot, no EEPROM write, no wear concern. It would give us exact overwrite counts within a boot. Without it we have the ring-wrap line, which tells us wrapping is happening but not how much.

---

## What changes on our side

**The response shrinks** from ~700 bytes to ~120, three fields:

```json
{"ok": true, "recorded": true, "stored_key": "diagnostics/<id>/2026/08/27/....txt"}
```

`recorded: false` means we already hold those exact bytes — still success, still safe to advance your delivered marker.

**Status codes are unchanged.** 200 = durably in S3, advance the marker. 4xx = stop retrying, keep the records. 503 = keep the records, retry.

**HTTP 500 should stop happening.** The 500s you saw on 2026-08-27 were a header field overflowing a database column on our side. With no header, that failure mode is gone. A 500 after this ships is a bug worth reporting.

---

## Withdrawn from spec v1.0

| Section | Requirement | Status |
|---|---|---|
| §3.3 | Delivered marker persisted across reboot | **withdrawn** |
| §3.4 | Monotonic 32-bit overflow counter, never reset | **withdrawn** |
| §4.1 | The `#VLTDIAG/1` header line | **withdrawn** |

§3.1 (write-protected config/identity block) and §3.2 (wear-levelled ring buffer) **still stand** — those protect the unit itself, not our accounting, and remain unconfirmed.

Without a persisted delivered marker the charger will re-send records after a reboot. Expected and fine — we de-duplicate server-side. It costs some redundant cellular data and nothing else.

---

## Defects we found, for your awareness

C3′ and C7 above are live. These three become moot once the header goes, but they are the same class of problem — a counter not surviving a reboot — so they may point at something worth checking elsewhere in the firmware.

- **`overflow` emitted with inconsistent sign.** Values arrived as `4294967295`, `4294967105`, `4294949196` — `-1`, `-191`, `-18100` in two's complement, written into an unsigned field. The magnitudes matched `first_record - 1` exactly, so the same quantity was being emitted with the wrong sign part of the time.
- **`seq` not incrementing between distinct bundles.** Four consecutive uploads covering four different ranges (`17396..`, `17474..`, `17531..`, `17584..`) all carried `seq=4`.
- **`boot` skipping and resetting.** Ran `54, 56, 58` — skipping 55 and 57 — then reset to `1`.

---

## One question we need answered

Which is your actual constraint?

**(a)** No persisted *counters* — but the ring buffer and its write head do survive a reboot.
**(b)** No persistence at all beyond raw buffer contents — the head pointer is volatile too.

ADR 0030 assumes **(a)**. If it is **(b)**, the charger re-sends its whole buffer every boot and we need record-level de-duplication rather than bundle-level — a larger change on our side. It changes nothing you need to do, but we need to know which it is.

---

## Checklist

- [ ] **C3′** `Meter E` totalizer redacted from ATM90E26 lines (V/I/PF/Freq may stay) — *carried over from v1.1, still outstanding*
- [ ] **C6** `#VLTDIAG/1` header line removed
- [ ] **C7** CSMS HTTP response no longer written to the ring buffer
- [ ] **C8** *(optional)* volatile since-boot `overflow=` record
- [ ] **C5b** Upload during an active charging session, with UTC timestamp reported — *carried over from v1.1*
- [ ] **Q1** Persistence constraint confirmed in writing: (a) or (b)
- [x] ~~**C1**~~ `TIME_SYNC` per boot segment — done, now load-bearing, do not regress
- [x] ~~**C5a**~~ ~192 KB upload — done 2026-08-21, 196,588 B, body intact
- [x] ~~**C2a**~~ / ~~**C2b**~~ / ~~**C4**~~ — withdrawn with the header

Everything in [spec v1.0](./diagnostic-bundle-upload-spec.md) not amended here or in v1.1 still stands.
