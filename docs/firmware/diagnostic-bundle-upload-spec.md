# Diagnostic Bundle Upload — Firmware Specification

> **Partly withdrawn (2026-08-27) — see [Required Changes v1.2](./diagnostic-bundle-required-changes-v1.2.md).**
> §3.3 (delivered marker persisted across reboot), §3.4 (monotonic overflow counter) and §4.1 (the `#VLTDIAG/1` header line) are **withdrawn**: all three require the charger to keep a counter across a reboot, which the hardware cannot do. §3.1 (write-protected config block), §3.2 (wear levelling) and §2.2 (nothing metering, no credentials, no raw RFID) **still stand**. The CSMS now reads `===== BOOT`, `TIME_SYNC boot_ms=… utc=…` and the ring-wrap line from the body instead.

**Version**: 1.0
**Date**: 2026-08-18
**Status**: Draft — for firmware team review. Section 9 lists items we still need answers on.
**Related**: [ADR 0029](../adr/0029-diagnostic-bundle-authenticated-https-upload.md), [ADR 0020](../adr/0020-charger-websocket-basic-auth.md)

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

A bundle is a **header line**, followed by log records.

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

Every line after the header is one log record per §2.1. There is no trailer and no checksum — TLS provides integrity.

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

#VLTDIAG/1 boot=17 seq=42 first=100234 last=102301 overflow=0
2026-08-18T03:12:44Z INFO  modem    registered on network, rssi=22
...
```

**TLS is required.** The host presents a Let's Encrypt certificate chaining to ISRG Root X1 — the same certificate the charger already validates on every OCPP WSS connection, so no trust store change is needed.

**Credentials.** The username is the charger's `charge_point_string_id` (the same UUID used as the OCPP WSS path segment). The password is the **Charger Auth Key**, a 20-byte secret provisioned per unit. It **MUST** be stored in the write-protected EEPROM region (§3.1). The CSMS holds only a SHA-256 hash — a lost key is rotated, never recovered.

**Size limit.** 2 MB. Uploads above this are rejected with `413`.

**Compression is optional.** If firmware can gzip the body, send `Content-Encoding: gzip`. Text logs compress roughly 6:1, which is a meaningful saving on cellular data. Plain text is entirely acceptable if a deflate implementation isn't readily available.

---

## 7. Handling the response

The **delivered marker advances on HTTP 2xx and nothing else.** Not on a successful TCP connect, not on a timeout, not on a 4xx. Anything else leaves those records undelivered, so the overflow counter keeps accounting for them honestly if they're later overwritten.

| Status | Meaning | Firmware action |
|---|---|---|
| `200` / `201` | Stored durably | Advance the delivered marker to `last` |
| `409` | This bundle was already received | Treat as success — advance the marker |
| `401` | Authentication failed | **Do not** advance. Stop retrying this cycle. Log locally. |
| `400` | Malformed header | **Do not** advance. Stop retrying this bundle. |
| `413` | Body too large | **Do not** advance. Stop retrying. Send a smaller range next cycle. |
| `429` | Rate limited | Retry after backoff |
| `5xx`, timeout, no link | Server or network problem | Retry per §7.1 |

A `401` **MUST NOT** discard data. A botched key rotation must not cost the buffer.

### 7.1 Retry policy

On a retryable failure: retry at approximately **+15 minutes**, then **+60 minutes**, then stop and wait for the next scheduled cycle.

Do not retry continuously. A CSMS outage lasting a day must not consume a day of cellular data. Records simply accumulate, and the overflow counter reports afterwards whether anything was actually lost.

A `409` on retry is expected and normal: it means the upload succeeded but the response was lost on the cellular link. Treat it as success.

---

## 8. Clock handling

Units set their RTC from `BootNotification.currentTime`, which gives log timestamps a trustworthy anchor. Two gaps remain.

**Records written before the first successful BootNotification carry an unset or stale clock.** This is worst exactly where it hurts most — a charger that cannot reach the CSMS logs its connection failures with a wrong clock. Firmware **SHOULD** emit a marker record when it adjusts the clock:

```
2026-08-18T03:12:51Z INFO  clock    CLOCK_SET from=2000-01-01T00:00:03Z to=2026-08-18T03:12:51Z
```

That single line lets the CSMS retroactively correct every earlier record in the same boot segment by the delta. Without it, the pre-connection window is permanently untimed.

**Setting time only at boot allows drift.** A cheap RTC drifts seconds per day, so a charger up for a month runs minutes off. `Heartbeat.conf` also carries `currentTime`; re-syncing from it bounds drift to the heartbeat interval at no extra cost. Firmware **SHOULD** do this.

---

## 9. Open questions for the firmware team

| # | Question | Why it matters |
|---|---|---|
| 1 | **Which modem** do these units carry — BG95/BG96, or EC25/EG21/EG25? | BG95/BG96 hold a single TLS context, so an HTTPS upload will suspend the OCPP WSS connection. We can suppress the resulting disconnect alarms, but only if we know to expect them. |
| 2 | Is the ring buffer's **write head wear-levelled**, or kept at a fixed address? | §3.2 — a fixed address fails in about two weeks, silently, in the field. |
| 3 | Does firmware currently log the **raw RFID card UID** on swipe? | §2.2 — needs masking at source before bundles start flowing. |
| 4 | Does firmware **print configuration at boot**, and could that include the Charger Auth Key? | §2.2 — would leak the credential into CSMS storage daily. |
| 5 | Can you add the **`CLOCK_SET` marker record** (§8)? | Recovers timing for the pre-connection window — one log line of work. |
| 6 | Can you **re-sync the clock from `Heartbeat.conf`** (§8)? | Bounds RTC drift on long-uptime units. |
| 7 | Is **gzip** available for the request body (§6)? | Optional. Roughly 6× less cellular data. |
| 8 | Could you support an inbound **`FlushDiagnostics` DataTransfer** in a later release (§5.3)? | Restores on-demand log retrieval. Far cheaper than `GetDiagnostics` — no `location` parsing, no file semantics, no FTP client. |

---

## 10. Implementation checklist

- [ ] Config, identity, and Charger Auth Key in the hardware write-protected EEPROM block; ring buffer in the remainder
- [ ] Ring buffer write head wear-levelled across pages
- [ ] Delivered marker, persisted across reboot
- [ ] Monotonic 32-bit overflow counter, never reset
- [ ] Boot counter and bundle sequence number, persisted across reboot
- [ ] Log records as UTF-8 text lines, UTC timestamps, `LEVEL` and `subsystem` fields
- [ ] No secrets, no raw card UIDs, no metering data in traces
- [ ] `#VLTDIAG/1` header line assembled correctly
- [ ] Six-hourly upload, offset derived from the charger's own identifier
- [ ] Fault-triggered upload with a 15-minute minimum interval
- [ ] HTTPS POST with Basic Auth to `app.voltlync.com`
- [ ] Delivered marker advances on 2xx only; `409` treated as success
- [ ] Retry at +15 min and +60 min, then wait for the next cycle
- [ ] `401` does not discard buffered records
- [ ] `CLOCK_SET` marker record on RTC adjustment
