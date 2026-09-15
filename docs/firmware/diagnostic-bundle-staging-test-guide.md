# Diagnostic Bundle Upload — Staging Test Guide

**Version**: 1.0
**Date**: 2026-08-18
**Audience**: Firmware team
**Companion to**: [Diagnostic Bundle Upload — Firmware Specification](./diagnostic-bundle-upload-spec.md)

## 1. What you're testing against

There is a **probe endpoint** live on staging. It is deliberately **not** the real endpoint:

- It **does not check your credentials** — any username and password are accepted.
- It **does not reject anything** for being wrong. Malformed headers, missing auth, binary junk: all return `200`.
- It **tells you exactly what arrived** — byte counts, line counts, parsed header fields, and a list of anything that looked wrong.

The point is to answer one question before either side builds the real thing: **can the charger's HTTP client reach us over TLS and deliver an intact body?** Everything else is secondary.

Nothing you send here is treated as production data. Send as many attempts as you like.

---

## 2. Sixty-second sanity check (do this first)

Before touching firmware, confirm the endpoint is reachable from any machine:

```bash
printf '#VLTDIAG/1 boot=1 seq=1 first=1 last=2 overflow=0\n2026-08-18T13:00:00Z INFO test hello\n' \
  | curl -s -X POST https://staging.voltlync.com/api/diagnostics/bundles \
      -u 'my-test-charger:anything' \
      -H 'Content-Type: text/plain; charset=utf-8' \
      --data-binary @-
```

You should get back JSON with `"ok": true` and `"warnings": []`. If that works, the server side is fine and any later failure is on the charger side — which is exactly the split you want before you start debugging firmware.

---

## 3. Endpoint

| | |
|---|---|
| **URL** | `https://staging.voltlync.com/api/diagnostics/bundles` |
| **Method** | `POST` |
| **Auth** | HTTP Basic. **Not validated** — but please send it anyway (see below). |
| **Content-Type** | `text/plain; charset=utf-8` |
| **Max body** | 2 MB |
| **Compression** | Optional. Send `Content-Encoding: gzip` if you can. |
| **TLS** | Required. Let's Encrypt (ISRG Root X1) — the same certificate the charger already validates on every OCPP WSS connection. |

**Send the Authorization header even though it isn't checked.** Whether your HTTP client can set an arbitrary header is itself one of the unknowns we're testing. Use the charger's `charge_point_string_id` as the username so uploads are attributable to a unit; the password can be any placeholder for now.

---

## 4. Reading the response

Every upload returns JSON describing what arrived. This is your debugging surface:

```json
{
  "ok": true,
  "received_bytes": 238,
  "decoded_bytes": 238,
  "content_encoding": null,
  "content_type": "text/plain; charset=utf-8",
  "user_agent": "QuectelHTTP/1.0",
  "client_ip": "49.37.233.66",
  "auth_username": "8f14e45f-ceea-467a-9575-1f0f1a0f0a0b",
  "record_count": 3,
  "header": { "boot": 17, "seq": 42, "first": 100234, "last": 100237, "overflow": 0 },
  "header_valid": true,
  "body_preview": "#VLTDIAG/1 boot=17 seq=42 ...",
  "stored_path": "s3://voltlync-diagnostics-staging/diagnostics/...",
  "warnings": []
}
```

| Field | What it tells you |
|---|---|
| `received_bytes` | Bytes that arrived on the wire. **Compare against what you sent** — a mismatch means truncation. |
| `decoded_bytes` | Bytes after gunzip. Same as `received_bytes` when not compressed. |
| `record_count` | Log lines received, excluding the header line. |
| `auth_username` | The username we decoded. `null` means your `Authorization` header never arrived. |
| `header` | Your `#VLTDIAG/1` fields, parsed as integers. |
| `header_valid` | `true` only if every required field was present and numeric. |
| `body_preview` | First 200 characters, so you can eyeball encoding problems. |
| `stored_path` | Where we archived it. A value starting `s3://` means it persisted successfully. |
| `warnings` | **The field that matters.** Empty means a clean upload. |

**A clean pass is `warnings: []` and `received_bytes` matching what you sent.**

---

## 5. Warnings and what they mean

| Warning | Cause | Fix |
|---|---|---|
| `no Authorization header — firmware must send HTTP Basic` | Header not sent, or stripped by your HTTP stack | Check your client supports custom headers |
| `Authorization is not Basic (got '...')` | Wrong auth scheme | Use `Basic base64(user:pass)` |
| `Authorization header is not valid base64/UTF-8` | Encoding bug | Base64-encode `username:password` as one string |
| `Authorization carries an empty password` | Trailing colon with nothing after it | Send a placeholder password |
| `first line is not a #VLTDIAG/1 header (got '...')` | Header line missing or misspelled | See spec §4.1 — it must be the literal first line |
| `header is missing seq=` | A required field was omitted | All of `boot`, `seq`, `first`, `last`, `overflow` are required |
| `header field seq='abc' is not an integer` | Non-numeric value | Send decimal integers, no quotes or units |
| `Content-Encoding: gzip declared but body did not decompress` | Header says gzip, body isn't | Either compress the body or drop the header |
| `body is not valid UTF-8 — decoded with replacement characters` | Binary data or wrong encoding | Log records must be UTF-8 text (spec §2.1) |

Warnings never fail the upload. They're diagnostics, and each one is a specific thing to fix.

---

## 6. Test phases

Run these in order. Each isolates one variable.

### Phase 1 — small payload, charger idle

Send roughly 10 KB while the charger is connected over OCPP and **not** charging.

**Check:** `ok: true`, `warnings: []`, `received_bytes` matches what you sent, `header_valid: true`, `auth_username` populated.

**Record the exact UTC timestamp of the upload** — see §7 for why this matters more than anything else in this document.

### Phase 2 — realistic payload

Send a full buffer, roughly 192 KB.

**Check:** everything from Phase 1, plus **how long the upload took**. Note it.

### Phase 3 — during an active charging session

Same as Phase 2, but start the upload while a vehicle is actively charging.

**Check:** everything above, and tell us whether the charging session continued normally.

This is the phase we care most about and the one most likely to reveal a problem. Don't skip it.

### Phase 4 — repeat and vary

Once the above pass, try: a reboot mid-upload, an upload with no network, an upload with gzip if you support it. We want to see the failure paths, not just the happy one.

---

## 7. What we're measuring that you can't see

**Whether the OCPP WebSocket connection drops during your upload.**

Some cellular modems (Quectel BG95/BG96) hold only one TLS context at a time, so opening an HTTPS connection suspends the WSS link. We can detect this from our side by correlating your upload against our disconnect events — but only if we know **when** each upload happened.

**So: for every test upload, send us the UTC timestamp.** A list like this is enough:

```
2026-08-20T04:12:33Z  phase 1  10 KB
2026-08-20T04:31:07Z  phase 2  192 KB, took 14s
2026-08-20T05:02:55Z  phase 3  192 KB, during active session
```

Without timestamps we cannot answer the modem question, and it's the single most consequential unknown in this design — it determines how often the charger can upload and whether uploads must be confined to overnight hours.

---

## 8. Troubleshooting

| Symptom | Likely cause |
|---|---|
| TLS handshake fails | Charger's CA store doesn't have ISRG Root X1. Unexpected — the same cert works for OCPP WSS — so check whether your HTTP client uses a *different* SSL context from your WebSocket client. On Quectel that's usually a separate `AT+QSSLCFG` profile. |
| Connection times out | DNS or routing. Confirm the modem resolves `staging.voltlync.com`. |
| `HTTP 404` | The probe is disabled. Tell us — it's a server-side flag. |
| `HTTP 413` | Body over 2 MB. Send a smaller range. |
| `HTTP 502` / `504` | Server-side problem, not yours. Tell us. |
| Upload succeeds but `received_bytes` is short | Truncation — check `Content-Length` matches the body you actually write. |
| `auth_username: null` | Your HTTP client isn't sending the header. |

---

## 9. A note on log content

**Send real traces.** We want to see what the buffer actually contains, not synthetic samples — the content is as informative as the transport.

Be aware that these land in our S3 archive, and we will read them. Specifically, we'll be checking for the two things the specification asks you to keep out (spec §2.2): **raw RFID card identifiers** and **any configuration dump containing the Charger Auth Key**. If they're present in current firmware that's useful to discover now rather than after bundles are flowing in production — it's not a problem for the test, it's one of the things the test is for.

Please don't send metering or energy values (spec §2.2).

---

## 10. When you're done, tell us

1. **Which modem** these units carry — BG95/BG96, or EC25/EG21/EG25.
2. **The UTC timestamp of every upload attempt** (§7).
3. **Upload duration** for the full-size payload.
4. **Whether the OCPP connection appeared to drop** from your side during any upload.
5. Whether the charging session in Phase 3 was affected.
6. Anything from spec §9 you can now answer — particularly whether the ring buffer's write head is wear-levelled, and whether firmware logs raw card UIDs or dumps config at boot.

The probe stays up until we've built the real endpoint. If it starts returning `404`, it's been turned off — ask us to re-enable it.
