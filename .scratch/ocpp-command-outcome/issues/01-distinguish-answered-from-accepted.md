# Make the OCPP send contract distinguish "answered" from "accepted"

Status: done

## What to build

`send_ocpp_request` returns `(True, response)` whenever the charger **replied**, and
callers overwhelmingly read that boolean as "the command worked". Those are different
claims. A **remote command** can come back `Refused` — a perfectly successful exchange
in which the answer was no.

Six of the eight call sites checked never look at the status. Only `ChangeAvailability`
(forced by [[adr-0008-charger-availability-separate-from-status]]) and the billing-path
`RemoteStopTransaction` get it right — the two places where correctness was compelled by
something else.

Introduce a **command outcome** at the transport seam so the three states cannot be
conflated. See `CONTEXT.md` → *Remote commands* for the vocabulary; note in particular
that **Refused** (the charger's no) is deliberately not called "rejected", which already
means *this server* refusing a charger's connection.

**Settled by design session, do not re-litigate:**

- A refusal is an **expected operational outcome, not an error**. No exception, no 5xx,
  no Sentry. The system worked; the answer was no.
- Three states: **Accepted** / **Refused** / **Unanswered**. `Accepted` absorbs OCPP's
  `Scheduled`, because the only caller that sees it already treats the two identically.
- **No boolean in the final contract.** A boolean whose meaning was ambiguous is the
  entire cause of this bug; replacing it with a differently-ambiguous boolean solves
  nothing. Callers ask a specific question instead.
- Retry policy and HTTP status are **not** decided here — they belong to the per-command
  tickets, which have different answers for QR (retries, refunds) than for the manual
  endpoints (fail fast, a human is present).

**Expand, don't break.** This ticket adds the outcome *alongside* the current
two-tuple so every existing call site keeps working and behaving identically; issues 02
and 03 migrate callers, and 04 removes the old shape. Keep the timeout at 30 seconds and
add no retry at this layer — retry is a caller's policy, not the transport's.

**One correctness trap.** Not every response carries a status: OCPP 1.6's
`UpdateFirmware.conf` is an empty payload. For those commands an answer *is* an
acceptance, and treating a missing status as a refusal would silently break firmware
updates.

## Acceptance criteria

- [ ] A caller can distinguish Accepted / Refused / Unanswered without string-sniffing or reaching into the raw response.
- [ ] `Scheduled` reports as Accepted; the raw wire status remains reachable for callers that surface it verbatim.
- [ ] A response with **no status field** (`UpdateFirmware`) reports as Accepted, not Refused.
- [ ] Every existing call site still works and behaves **exactly** as before — this ticket changes no observable behaviour.
- [ ] The Unanswered state is distinguishable from Refused without parsing the `"OCPP timeout"` string the admin endpoint currently sniffs for.
- [ ] Unit tests cover all three states plus the empty-payload case.
- [ ] `docker exec ocpp-backend pytest` passes for the affected files against the documented baseline.

## Blocked by

None — can start immediately.

## Comments

**2026-09-02 — done.** `CommandOutcome` added at the transport seam in
`core/connection_manager.py`; `send_ocpp_request` returns it and still unpacks as the
historical `(success, response)` pair, so no call site changed behaviour.

Design settled in a grilling session before any code: a refusal is an expected outcome
rather than an error, `Scheduled` is absorbed into Accepted, and `Refused` is kept
distinct from `Rejected` because that word already means *this server* refusing a
charger connection. Vocabulary is in `CONTEXT.md` under **Remote commands**.

One trap encoded in a test: `UpdateFirmware.conf` is an empty payload, so a missing
status must read as Accepted — treating it as a refusal would silently break firmware
updates.

Verified: 14 new tests in `tests/test_command_outcome.py`, plus 171 regression tests
green across `test_chargers` (28), `test_qr_payment_service` (83),
`test_franchisee_portal` (19), `test_ocpp_message_type` (24),
`test_firmware_update_service` (9) and `test_disconnect_handler` (8).

Issues 02 and 03 are now unblocked and can run in parallel.
