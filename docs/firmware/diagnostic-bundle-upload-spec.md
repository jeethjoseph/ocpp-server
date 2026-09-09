# Diagnostic Bundle Upload — Firmware Specification

> **What changed in 2.0 — read this before implementing.**
>
> **The body is the whole contract.** A bundle is newline-delimited log records and nothing
> else. Three sections are **withdrawn**, and they are left in place struck through rather
> than deleted so you can see what changed and why:
>
> | Withdrawn | Why |
> |---|---|
> | §3.3 Delivered marker | requires cross-reboot persistence the hardware cannot provide |
> | §3.4 Overflow counter | same — a monotonic counter cannot survive the reboot it exists to survive |
> | §4.1 `#VLTDIAG/1` header | every field in it came from those two counters |
>
> All three asked the charger to keep a counter across a reboot, separately from the data it
> describes. It cannot. Rather than ask for it again in a different shape, the CSMS now reads
> what the firmware **already emits in-band** — see the new **§4.3**, which promotes three
> existing log lines to contractual status. If you have implemented against 1.0, the work to
> withdraw is real but small; §4.3 should need no new code at all.
>
> **Still standing, unchanged:** §3.1 (write-protected config block), §3.2 (wear levelling)
> and §2.2 (nothing metering, no credentials, no raw RFID). §2.2 is *reinforced* in 2.0.

**Version**: 2.0
**Date**: 2026-09-08
**Supersedes**: 1.0 (2026-08-18)
**Status**: Draft — for firmware team review. Section 9 lists items we still need answers on.
**Related**: [ADR 0030](../adr/0030-diagnostic-bundle-body-is-the-contract.md) (why the header went), [ADR 0029](../adr/0029-diagnostic-bundle-authenticated-https-upload.md), [ADR 0020](../adr/0020-charger-websocket-basic-auth.md)

## 1. Overview

The charger buffers its internal firmware debug traces in on-board EEPROM and uploads them periodically to the CSMS as an HTTPS POST. The CSMS archives each upload and indexes the individual log lines so they can be searched across the whole fleet.

**OCPP `GetDiagnostics` is not used.** This channel is deliberately outside OCPP — no `GetDiagnostics`, no `DiagnosticsStatusNotification`, no FTP.

One upload is called a **Diagnostic Bundle**.

Requirement keywords **MUST**, **MUST NOT**, **SHOULD**, and **MAY** are used in the RFC 2119 sense.

---

## 2. What goes in the buffer

### 2.1 Format

Log records **MUST** be plain UTF-8 text, one record per line, `\n`-terminated.

Each line **SHOULD** follow:

```
<ISO8601-UTC> <LEVEL> <subsystem> <message>
```

Example:

```
2026-08-18T03:12:44Z INFO  modem    registered on network, rssi=22
2026-08-18T03:12:51Z INFO  ocpp     BootNotification accepted
2026-08-18T14:31:02Z ERROR relay    contactor feedback mismatch, expected=CLOSED read=OPEN
2026-08-18T14:31:02Z WARN  ocpp     StatusNotification Faulted errorCode=OtherError
```

- Timestamp is **UTC** with a `Z` suffix. Do not use local time.
- `LEVEL` is one of `DEBUG`, `INFO`, `WARN`, `ERROR`.
- `subsystem` is a short token with no spaces.
- `message` is free text and **MUST NOT** contain a newline.

Lines that don't match this shape are still accepted and stored — they are simply less useful. Nothing is dropped for being unparseable.

### 2.2 What MUST NOT be logged

These three exclusions are not stylistic. Each one prevents a specific, concrete failure.

**Secrets — including the Charger Auth Key.** Firmware **MUST NOT** print credentials, keys, or config dumps containing them. Boot-time configuration dumps are the usual culprit. The CSMS stores only a hash of the auth key and reveals the plaintext exactly once at provisioning; if the key appears in a trace, that protection is void and the credential ends up in two external systems on a daily schedule.

**Raw RFID card identifiers.** When a customer swipes, firmware **MUST** mask the card UID before logging it — first two and last two characters at most, e.g. `A1****9F`. A card UID is a customer identifier. The CSMS already masks this value in its own logs; an unmasked copy arriving from the charger would undo that.

**Metering and energy data.** kWh readings, meter totalizer values, tamper events, and calibration events **MUST NOT** appear in this stream. Energy reaches the CSMS through `MeterValues` and `StartTransaction`/`StopTransaction`, which are the audited billing path. A second, unaudited copy creates a compliance problem the moment the two disagree.

> **Reinforced in 2.0 — this one is not yet being met.** The CSMS runs a redactor over every
> bundle as a second line of defence, and it is currently stripping **~28 meter values per
> bundle**. That is measured, not hypothetical: firmware-side redaction is under-matching
> today.
>
> The server-side redactor is a backstop, **not a licence to emit**. It matches patterns it
> knows about; anything shaped slightly differently goes to storage. And the exclusion is not
> about tidiness — it is what keeps a Diagnostic Bundle *disposable observability data*
> rather than unaudited legal-metrology data sitting next to a GST Invoice. Please close the
> gap at source.

---

## 3. EEPROM buffer requirements

### 3.1 Memory partitioning

The EEPROM holds both the charger's configuration and identity **and** this log buffer. They **MUST** be separated:

- Configuration, identity, calibration constants, and the **Charger Auth Key** go in a **hardware write-protected block** (the M24M02 supports write protection by ¼, ½, or whole array).
- The log ring buffer goes in the unprotected remainder.

This is what stops a pointer bug in the logging code from destroying the charger's own credential and identity — the difference between "a logging bug loses logs" and "a logging bug bricks the unit".

### 3.2 Wear levelling

The ring buffer's write head **MUST** be wear-levelled across pages.

A head pointer kept at a fixed EEPROM address takes every single write. The part is rated for >4 million write cycles at 25 °C but only **1.2 million at 85 °C**, and a sealed enclosure in summer sits near the top of that range. At one record per second, a fixed-address pointer fails in roughly **two weeks** — silently, in the field, after warranty. Distributing writes across all 1,024 pages instead gives decades of margin at any realistic logging rate.

### 3.3 Delivered marker

> **WITHDRAWN 2026-08-27** — requires cross-reboot persistence the hardware cannot provide. The charger may re-send after a reboot; the CSMS de-duplicates on a content digest.

Firmware **MUST** maintain a **delivered marker**: the record number up to which the CSMS has confirmed receipt. It **MUST** persist across reboot.

- Records at or below the marker may be overwritten freely.
- Records above the marker that get overwritten **MUST** increment the overflow counter (§3.4).

### 3.4 Overflow counter

> **WITHDRAWN 2026-08-27** — same reason. The in-band `ring wrapped mid-upload` line replaces it as a *recency* signal; the cumulative total is not recoverable.

Firmware **MUST** maintain a 32-bit **overflow counter**: the running total of records overwritten *before* they were delivered.

It **MUST** be monotonic — incrementing only, never reset, wrapping at 32 bits. The CSMS computes each bundle's losses by differencing against the previous bundle's value.

Do not reset it after a successful upload. A reset counter loses its evidence in exactly the case that matters: if a bundle goes missing in transit, it takes its loss count with it and the data loss becomes invisible again.

This counter is what turns silent data loss into a visible, alertable event. Without it, a charger that faults and floods its own buffer delivers only the tail of the retry noise, with nothing indicating the root cause was overwritten — and whoever reads it will date the fault wrongly and with confidence.

---

## 4. Bundle format

A bundle is **log records and nothing else** — newline-delimited UTF-8, first line to last.
There is no header, no trailer and no checksum; TLS provides integrity.

Identity, time and loss are all derived from the body. §4.3 is therefore the load-bearing
part of this specification.

### 4.1 Header line

> **WITHDRAWN 2026-08-27** — the body is the whole contract. A bundle starts with its first log record.

The first line of the body:

```
#VLTDIAG/1 boot=<uint32> seq=<uint32> first=<uint32> last=<uint32> overflow=<uint32>
```

| Field | Meaning |
|---|---|
| `#VLTDIAG/1` | Magic and format version. Increment the version on any format change. |
| `boot` | Boot counter, incremented each cold start, persisted across reboot. |
| `seq` | Bundle sequence number, incremented per upload attempt that produces a new bundle, persisted across reboot. |
| `first` | Record number of the first record in this bundle. |
| `last` | Record number of the last record in this bundle. |
| `overflow` | Current value of the monotonic overflow counter (§3.4). |

Example:

```
#VLTDIAG/1 boot=17 seq=42 first=100234 last=102301 overflow=0
```

### 4.2 Body

Every line is one log record per §2.1. A body whose first line is no longer `#VLTDIAG/1 ...`
is just a body; nothing special happens, and there is no header to be valid or invalid.

A leading `#VLTDIAG/` line from firmware still running 1.0 is tolerated and ignored. It is
stripped before the content digest is taken — it was the only part of a retried bundle that
changed between attempts, so hashing it in meant retries never de-duplicated (observed: three
retries of 460 identical lines producing three different digests, differing only in `last=`).

### 4.3 Required in-band records

**These three lines are the contract.** All three already exist in shipped firmware; this
section makes them contractual rather than incidental, because the CSMS now derives a
bundle's identity, its time window and its loss signal entirely from them. **A change to any
of these formats is a breaking change and MUST be raised before it ships.**

#### Boot marker — MUST, on every cold start

```
===== BOOT @278 ms, reset reason 3 =====
```

Matched on `===== BOOT`, case-insensitive. An optional `n=<uint32>` is read as a boot counter
if present; its absence is fine and is what shipped firmware currently emits.

This delimits one boot's records from the next. The CSMS anchors each boot segment against
**its own** clock anchor, never a bundle-wide one — which is precisely what stops a reboot
being reported as data loss.

#### Clock anchor — MUST, on every clock set and every re-sync

```
TIME_SYNC boot_ms=17673 utc=2026-08-19T12:02:05Z
```

`boot_ms` is milliseconds since this boot; `utc` is ISO 8601 with a `Z` suffix. Both fields
are required, and `boot_ms` is the important one: it is what lets the CSMS reconstruct real
timestamps for every record in the segment **including those written before the sync**, by
differencing against each record's own boot-relative offset.

That retroactive anchoring is the whole point. A charger that cannot reach the network logs
its connection failures with an unset clock — the worst case, and exactly the one that
matters. One `TIME_SYNC` line on reconnect recovers all of it.

A segment with no anchor is **not an error**. The CSMS marks its window approximate and then
deliberately *refuses* to compute a loss gap against it, rather than inventing one.

The older free-text form `Time synced from heartbeat: <iso>` is still accepted so pre-C1 units
keep anchoring, but it carries no `boot_ms` and so cannot anchor records written before it.
New firmware **MUST** emit the `TIME_SYNC` form.

#### Ring-wrap line — MUST, when the buffer overwrites during an upload

```
DiagUpload: body short by 80 B (ring wrapped mid-upload)
```

Matched on the stable substring **`ring wrapped mid-upload`**, which **MUST NOT** change.
Surrounding text is free-form; that phrase is the contract.

Read it as a **recency** signal — records are being destroyed *right now* — and never as a
total. How much has been overwritten cumulatively is **not recoverable and will not be asked
for again**: that is exactly what §3.4 requested, and the hardware cannot provide it. Please
do not attempt to reconstruct it; a wrong total is worse than an honest "unknown".

---

## 5. When to upload

### 5.1 Scheduled — every 6 hours, staggered

Four uploads per day, at approximately **6-hour intervals**.

The offset within each window **MUST** be derived deterministically from the charger's own identifier (for example, `minutes = hash(charge_point_string_id) mod 360`), not chosen randomly at each boot and not fixed across the fleet. A shared upload time would put every charger on the endpoint in the same minute.

**Why 6 hours and not nightly.** The CSMS indexes each record using the timestamp the charger assigned it, and the indexing backend **discards any record already older than 48 hours** — silently, with no error returned. A once-daily upload leaves the oldest records ~24 hours old, which is fine until a cycle fails: the retry falls through to the next day, the oldest records reach ~48 hours, and they vanish from search while still appearing to have uploaded successfully. A 6-hour cadence keeps every record far inside that window even after a failed cycle. Total data volume is unchanged — only the number of requests goes up.

Faster than 6 hours is welcome if it's convenient at your end; slower is not.

### 5.2 Event-triggered — on fault

The charger **SHOULD** also upload shortly after entering a fault state.

This is the higher-value trigger. A faulting charger logs far harder than usual and can wrap its buffer within hours, overwriting the root cause before the nightly upload runs. Uploading on fault captures the trace while the cause is still in the buffer.

Guard it with a minimum interval of **15 minutes** between fault-triggered uploads so a unit stuck in a fault loop doesn't upload continuously. The server additionally rate-limits to ~6 uploads/hour per charger.

### 5.3 No server-initiated flush

The CSMS has no way to request an upload on demand in this version. If firmware capacity allows it later, the intended mechanism is an inbound OCPP `DataTransfer` with `vendorId=VoltLync`, `messageId=FlushDiagnostics` — see §9.

---

## 6. The HTTP request

```
POST /api/diagnostics/bundles HTTP/1.1
Host: app.voltlync.com
Authorization: Basic <base64(charge_point_string_id ":" charger_auth_key)>
Content-Type: text/plain; charset=utf-8
Content-Length: <n>

===== BOOT @278 ms, reset reason 3 =====
2026-08-18T03:12:44Z INFO  modem    registered on network, rssi=22
2026-08-18T03:12:51Z INFO  clock    TIME_SYNC boot_ms=17673 utc=2026-08-18T03:12:51Z
...
```

The body starts at the first log record. No header line.

**TLS is required.** The host presents a Let's Encrypt certificate chaining to ISRG Root X1 — the same certificate the charger already validates on every OCPP WSS connection, so no trust store change is needed.

**Credentials.** The username is the charger's `charge_point_string_id` (the same UUID used as the OCPP WSS path segment). The password is the **Charger Auth Key**, a 20-byte secret provisioned per unit. It **MUST** be stored in the write-protected EEPROM region (§3.1). The CSMS holds only a SHA-256 hash — a lost key is rotated, never recovered.

**Size limit.** 2 MB. Uploads above this are rejected with `413`.

**Compression is optional.** If firmware can gzip the body, send `Content-Encoding: gzip`. Text logs compress roughly 6:1, which is a meaningful saving on cellular data. Plain text is entirely acceptable if a deflate implementation isn't readily available.

---

## 7. Handling the response

**The response is a minimal ack.** As of 2.0 a success returns only:

```json
{"ok": true, "recorded": true, "stored_key": "..."}
```

`recorded` is `false` when the CSMS already held this exact body — a retry that succeeded the
first time but whose response was lost. Treat it as success.

> **Do not write the response body into the ring buffer.** Logging it costs buffer space on
> every upload, and it is the one thing in the system guaranteed to be uninteresting: it says
> a thing you already know, in records that then displace records you do not. It also feeds
> the next bundle its own previous ack.

**Release the records you just sent on HTTP 2xx and nothing else.** Not on a successful TCP
connect, not on a timeout, not on a 4xx. Anything else means those records did not arrive, and
overwriting them loses them silently.

(1.0 called this "advancing the delivered marker". The marker as a *persisted, cross-reboot*
structure is withdrawn — §3.3 — but the in-flight rule is unchanged: a 2xx, and only a 2xx,
means the CSMS has the bytes durably.)

**Corrected in 2.0 — the table below now matches what the endpoint actually returns.** 1.0
documented a `409` that is never sent, and omitted `404` and `503` that are.

| Status | Meaning | Firmware action |
|---|---|---|
| `200` | Stored durably (`"recorded": true`) | Success — those records may be overwritten |
| `200` | Already held (`"recorded": false`) | **Also success.** The CSMS de-duplicates on the content digest of the body; a lost response is the usual cause. Do not treat as an error |
| `401` | Authentication failed | **Do not** release. Stop retrying this cycle. Log locally |
| `404` | Charger not recognised, or no auth key provisioned | **Do not** release. Stop retrying. Needs provisioning at the CSMS end |
| `413` | Body too large (2 MB limit) | **Do not** release. Stop retrying. Send a smaller range next cycle |
| `429` | Rate limited (~6 uploads/hour/charger) | Retry after backoff per §7.1 |
| `503` | CSMS could not archive it durably | Retry per §7.1. This is deliberate: no 2xx is returned until the bytes are safe in S3 |
| `5xx`, timeout, no link | Server or network problem | Retry per §7.1 |

There is **no `409`**. An upload of a body already held returns `200` with
`"recorded": false`.

A `401` **MUST NOT** discard data. A botched key rotation must not cost the buffer.

### 7.1 Retry policy

On a retryable failure: retry at approximately **+15 minutes**, then **+60 minutes**, then stop and wait for the next scheduled cycle.

Do not retry continuously. A CSMS outage lasting a day must not consume a day of cellular data. Records simply accumulate; if the buffer wraps while that is happening, the ring-wrap line (§4.3) says so.

A retry of a body the CSMS already holds is expected and normal — it means the upload
succeeded but the response was lost on the cellular link. It returns `200` with
`"recorded": false`, de-duplicated on the content digest of the body. Treat it as success.

---

## 8. Clock handling

Units set their RTC from `BootNotification.currentTime`, which gives log timestamps a trustworthy anchor. Two gaps remain.

**Records written before the first successful BootNotification carry an unset or stale clock.** This is worst exactly where it hurts most — a charger that cannot reach the CSMS logs its connection failures with a wrong clock. Firmware **SHOULD** emit a marker record when it adjusts the clock:

```
2026-08-18T03:12:51Z INFO  clock    CLOCK_SET from=2000-01-01T00:00:03Z to=2026-08-18T03:12:51Z
```

That single line lets the CSMS retroactively correct every earlier record in the same boot
segment by the delta. Without it, the pre-connection window is permanently untimed.

**In 2.0 this is no longer a SHOULD in a corner of §8 — it is contractual.** Emit it in the
`TIME_SYNC boot_ms=<n> utc=<iso>` form of §4.3, which carries the boot-relative offset the
retroactive correction needs. The free-text `CLOCK_SET` line above anchors nothing.

**Setting time only at boot allows drift.** A cheap RTC drifts seconds per day, so a charger up for a month runs minutes off. `Heartbeat.conf` also carries `currentTime`; re-syncing from it bounds drift to the heartbeat interval at no extra cost. Firmware **SHOULD** do this.

---

## 9. Open questions for the firmware team

| # | Question | Why it matters |
|---|---|---|
| 1 | **Which modem** do these units carry — BG95/BG96, or EC25/EG21/EG25? | BG95/BG96 hold a single TLS context, so an HTTPS upload will suspend the OCPP WSS connection. We can suppress the resulting disconnect alarms, but only if we know to expect them. |
| 2 | Is the ring buffer's **write head wear-levelled**, or kept at a fixed address? | §3.2 — a fixed address fails in about two weeks, silently, in the field. |
| 3 | Does firmware currently log the **raw RFID card UID** on swipe? | §2.2 — needs masking at source before bundles start flowing. |
| 4 | Does firmware **print configuration at boot**, and could that include the Charger Auth Key? | §2.2 — would leak the credential into CSMS storage daily. |
| 5 | ~~Can you add the **`CLOCK_SET` marker record** (§8)?~~ **Answered** — shipped firmware emits `TIME_SYNC boot_ms=… utc=…`, now contractual in §4.3. | — |
| 6 | ~~Can you **re-sync the clock from `Heartbeat.conf`** (§8)?~~ **Answered** — observed on real traffic; keep doing it, and emit a `TIME_SYNC` line each time. | — |
| 9 | **Will the three §4.3 record formats stay stable?** If any is likely to change, say so now. | They are the whole contract as of 2.0. A silent format change breaks identity, timing or loss detection with no error anywhere. |
| 7 | Is **gzip** available for the request body (§6)? | Optional. Roughly 6× less cellular data. |
| 8 | Could you support an inbound **`FlushDiagnostics` DataTransfer** in a later release (§5.3)? | Restores on-demand log retrieval. Far cheaper than `GetDiagnostics` — no `location` parsing, no file semantics, no FTP client. |

---

## 10. Implementation checklist

**Storage**
- [ ] Config, identity, and Charger Auth Key in the hardware write-protected EEPROM block; ring buffer in the remainder
- [ ] Ring buffer write head wear-levelled across pages

**Content**
- [ ] Log records as UTF-8 text lines, UTC timestamps, `LEVEL` and `subsystem` fields
- [ ] No secrets, no raw card UIDs, **no metering data** in traces — see the reinforcement in §2.2, this is currently not met
- [ ] Response bodies **not** written into the ring buffer (§7)

**The three contractual in-band records (§4.3)**
- [ ] `===== BOOT` on every cold start
- [ ] `TIME_SYNC boot_ms=<n> utc=<iso8601Z>` on every clock set **and** every re-sync
- [ ] Ring-wrap line carrying the exact substring `ring wrapped mid-upload`

**Upload**
- [ ] Six-hourly upload, offset derived from the charger's own identifier
- [ ] Fault-triggered upload with a 15-minute minimum interval
- [ ] HTTPS POST with Basic Auth to `app.voltlync.com`
- [ ] Body starts at the first log record — **no header line**
- [ ] Retry at +15 min and +60 min, then wait for the next cycle
- [ ] `401` does not discard buffered records

**Withdrawn in 2.0 — do not implement**
- [x] ~~Delivered marker, persisted across reboot~~ (§3.3)
- [x] ~~Monotonic 32-bit overflow counter, never reset~~ (§3.4)
- [x] ~~Boot counter and bundle sequence number, persisted across reboot~~ (§4.1)
- [x] ~~`#VLTDIAG/1` header line assembled correctly~~ (§4.1)
