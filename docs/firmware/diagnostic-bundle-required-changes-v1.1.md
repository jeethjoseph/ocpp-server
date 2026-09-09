# Diagnostic Bundle — Required Changes (v1.1)

**Date**: 2026-08-19
**Audience**: Firmware team
**Based on**: staging upload `boot=3 seq=1`, 32,007 bytes, 608 lines, received 2026-08-19T12:03:38Z
**Amends**: [Diagnostic Bundle Upload — Firmware Specification v1.0](./diagnostic-bundle-upload-spec.md)

Everything below comes from reading the bundle you actually uploaded. Each item quotes your own log lines.

---

## What already works — please don't regress it

- **Transport is solved.** 32 KB over HTTPS, `warnings: []`, body arrived byte-intact.
- **The Authorization header works.** `auth_username` decoded correctly, so your HTTP client can set custom headers.
- **The OCPP connection survives the upload.** We correlated four uploads against our disconnect events — the WSS link stayed up for 158s, 371s, 554s and 752s afterwards. The EC200U handles a concurrent HTTPS socket fine. (Still untested at ~192 KB — see C5.)
- **Redaction exists and works for two of three categories:**
  ```
  DiagUpload: bundle 1, records 1..68, 16494 B body (redacted: 0 idTag, 0 credential, 0 meter)
  ```
  No card identifiers and no credentials in the body. Both confirmed by independent scan on our side.

---

## C1 — A bundle spans multiple boots, and the clock resets at each one

**Severity: blocker.** Without this, no log line can be placed in time.

Your bundle contained **three** boot cycles:

```
line   2:  ===== BOOT @254 ms, reset reason 1 =====
line  80:  ===== BOOT @255 ms, reset reason 3 =====
line 383:  ===== BOOT @255 ms, reset reason 3 =====
```

Line timestamps are milliseconds since **that** boot, so they restart at every marker. Your two time-sync lines demonstrate the consequence:

```
line 306:  I (17673) EC200U: Time synced from heartbeat: 2026-08-19T12:02:05Z
line 609:  I (19763) EC200U: Time synced from heartbeat: 2026-08-19T12:03:20Z
```

- boot-clock delta: **2.09 s**
- wall-clock delta: **75 s**

They disagree by 73 seconds because they belong to different boot cycles. Any server-side attempt to anchor `I (N)` to wall clock across the bundle produces wrong times — silently.

### What we need

**1. Keep the BOOT marker exactly as it is.** ~~Add a boot counter~~ — **withdrawn 2026-08-20.** Your existing marker is enough:

```
===== BOOT @254 ms, reset reason 1 =====
```

We split segments on it, and the bundle header already carries `boot=`, so a counter in the marker would be redundant. Which boot a segment belongs to is metadata the timestamp arithmetic never uses — each segment is anchored by its own `TIME_SYNC` regardless.

**2. Add one time-sync line per boot segment**, in a stable parseable form, once the clock is set — this is the only change needed for C1:

```
I (17673) CLOCK: TIME_SYNC boot_ms=17673 utc=2026-08-19T12:02:05Z
```

Given those two, we reconstruct wall-clock for every line server-side:

```
utc(line) = utc_anchor − boot_ms_anchor + line_ms
```

**You do not need to reformat your log lines.** Keep `I (683) TAG: message` exactly as it is. We only need the segment boundaries and one anchor per segment. This supersedes the ISO8601-per-line requirement in spec §2.1 — that requirement is withdrawn.

**3. Lines before the clock is set in a segment** are expected and fine. We shift them by the same delta once the anchor appears. A segment with **no** anchor at all (charger never reached the server that boot) will be marked approximate — which is acceptable, but tell us if that case is common.

---

## C2 — The ring buffer wrapped mid-upload, was padded, and `overflow` stayed 0

**Severity: blocker.** This is silent data loss, which is the one thing the bundle header exists to prevent.

Your own log records it:

```
W (32463) EC200U: DiagUpload: body short by 246 B (ring wrapped mid-upload) — padding
```

While the header of that same bundle claims:

```
#VLTDIAG/1 boot=3 seq=1 first=1 last=133 overflow=0
```

**246 bytes were lost and `overflow` reported zero.** Two separate problems:

1. **The overflow counter isn't counting wraps that occur during upload read-out.** Spec §3.4 requires it to count *every* record overwritten before delivery, including ones overwritten while the upload is in flight.
2. **Padding hides the loss.** Padding bytes are indistinguishable from data on our side. We would have read that bundle as complete.

### What we need

- Increment the overflow counter when the ring wraps past un-delivered records **during** upload, not only during normal logging.
- **Do not pad.** Send the short body and let the header's `first`/`last` and `overflow` describe what happened. A short body is honest; a padded body is not.
- If you want to signal it explicitly, emit the warning line into the bundle as you already do — but the header must agree with it.

Freezing the read range before starting the upload (snapshot the head/tail, then read) would avoid the wrap entirely and is the cleaner fix if it's practical.

---

## C3 — Metering totalizer is not being redacted

**Severity: must fix before production.**

19 lines of this form were in the bundle:

```
I (11473) ATM90E26: [AVERAGED] V: 239.12 V | I: 0.00 A | P(V*I): 0.00 W |
                    Active Power: 0.00 W | PF: 0.325 | Freq: 50.05 Hz | Meter E: 0.00000 kWh
```

Your redactor reported `0 meter` for the same bundle, so these lines aren't matching its rules.

**The specific field that must go is `Meter E`** — the cumulative energy totalizer. Energy reaches us through `MeterValues` and `StartTransaction`/`StopTransaction`, which is the audited billing path; a second unaudited copy arriving through diagnostics creates a compliance problem the moment the two disagree.

**Voltage, current, power factor and frequency can stay.** They're device-health telemetry, genuinely useful for diagnosis, and carry no billing meaning. We're not asking you to drop the whole line — just the totalizer field.

---

## C4 — Confirm what `first` and `last` count

Your bundle reported `first=1 last=133` with 608 lines in the body, and elsewhere logs `records 1..68, 16494 B body`. So a "record" appears to be a multi-line chunk rather than a line.

That's fine — but our gap detection keys off `first`/`last`, so we need it stated:

- Is a **record** one buffer entry that may contain multiple newlines?
- Is the counter monotonic across boots, or does it reset with the ring?

If it resets per boot, say so — it changes how we detect gaps between bundles.

*(No change may be needed here; we need the semantics confirmed, not altered.)*

---

## C5 — Still to test

- **A full-size bundle (~192 KB).** 32 KB is a good result but doesn't stress the modem. The known risk on EC2x parts is WSS keepalive starving under sustained upload throughput, and 32 KB is too small to trigger it.
- **An upload during an active charging session.** Every upload so far had `had_active_transaction: False`.

Please send the **UTC timestamp of each attempt** so we can correlate against our disconnect events — that correlation is how we confirm the modem behaviour, and we can't do it without the times.

---

## Checklist

- [ ] **C1** One parseable `TIME_SYNC boot_ms=… utc=…` line per boot segment when the clock is set (BOOT marker unchanged)
- [ ] **C2a** Overflow counter increments on wraps during upload read-out
- [ ] **C2b** Stop padding short bodies; header must agree with what was sent
- [ ] **C3** `Meter E` totalizer redacted from ATM90E26 lines (V/I/PF/Freq may stay)
- [ ] **C4** Record vs line semantics confirmed in writing
- [ ] **C5a** ~192 KB upload attempted, with UTC timestamp reported
- [ ] **C5b** Upload during an active charging session, with UTC timestamp reported

Everything in [spec v1.0](./diagnostic-bundle-upload-spec.md) not amended above still stands — in particular the EEPROM partitioning and wear-levelling requirements in §3, which remain unconfirmed.
