# Bring the remaining callers over and remove the ambiguous return

Status: done

## ELI5

When we send a charger a command it answers twice over: *"I heard you"* and *"I'll do it"*.
Those are different things — a charger can perfectly well acknowledge a command and then refuse
it. The old code treated them as the same.

Issues 01–03 fixed that for starting and stopping a charge. `Reset` still conflates them, so an
operator can hit "reboot this charger", see a success message, and the charger never reboots —
then they spend the afternoon debugging a unit they believe was power-cycled. This brings the
remaining callers over and deletes the ambiguous return shape so the conflation cannot creep
back in.

## What to build

The contract half of the expand/contract begun in issue 01. Migrate the call sites not
covered by issues 02 and 03 — `Reset` from the admin and franchisee paths, and any
other command still reading the old boolean — then delete the ambiguous return shape so
the conflation cannot reappear.

A `Reset` that the charger refuses is the same class of silent failure as a refused
stop: the operator believes the charger was power-cycled when it was not.

## Acceptance criteria

- [x] Every `send_ocpp_request` caller acts on the charger's verdict, or documents in code why the verdict is genuinely irrelevant for that command.
- [x] The old ambiguous return shape is gone; a caller cannot mistake "answered" for "accepted".
- [x] `ChangeAvailability` behaviour is unchanged — it already honours `Accepted`/`Scheduled` per ADR 0008 and must keep doing so.
- [x] Full backend suite run per-file per CLAUDE.md, against the documented baseline.
- [x] `docs/v1/llm-context-document.md` and `docs/v1/comprehensive-architecture-documentation.md` record the outcome contract.

## Blocked by

- `01-distinguish-answered-from-accepted.md`
- `02-remote-start-honours-rejection.md`
- `03-remote-stop-honours-rejection.md`

**2026-09-08 — shipped. Series complete 4/4.**

All eleven remaining callers migrated, then the tuple shape deleted: `CommandOutcome` is a
frozen dataclass, so `success, response = ...` now raises `TypeError`. That is the point —
a plain boolean is what made "answered" and "agreed" look alike, and nothing should be able
to reintroduce it quietly.

**Acted on the verdict (behaviour changed):**

- `chargers.reset_charger` — the headline case. A refused `Reset` returned
  `{"success": true, "message": "Hard reset command sent successfully"}` *and* wrote a
  `charger.reset` audit event. The audit record was the worse half: a durable false claim
  someone reads back months later. Now 409 on refusal, 504 on silence, and the audit event
  only on acceptance, carrying the OCPP status.
- `franchisee_portal.reset_charger` — same trap, same fix.
- `main.send_command_to_charge_point` — generic passthrough; reports the verdict rather than
  guessing what a refusal means for an arbitrary command. Unanswered moves 400 → 504.

**Migrated, behaviour deliberately unchanged:**

- Both `ChangeAvailability` handlers. `Scheduled` remains an acceptance and only
  Accepted/Scheduled persist operator intent (ADR 0008). The explicit `("Accepted",
  "Scheduled")` tuple is kept rather than `is_accepted`, so it stays visibly tied to ADR 0008
  instead of to a shared status set that could drift later.
- `firmware_update_service` — `UpdateFirmware.conf` is an empty payload in OCPP 1.6, so there
  is no status to refuse with and an answer *is* an acceptance. `is_accepted` already encodes
  that; reading the missing status as a refusal would have broken every firmware update.
- `qr_payment_service` RemoteStart — already drew the distinction by hand, which is why it
  behaved correctly. Now reads it from the outcome instead of re-deriving it from the payload.

**Verdict documented as irrelevant, per the acceptance criteria:**

The three at-least-once dispatchers — wallet budget cap, QR auto-stop, zero-energy watchdog —
plus the best-effort admin force-stop. Control flow is unchanged on purpose: energy is
monotonic, so a refused or lost stop self-heals on the next MeterValues tick, and duplicate
RemoteStops are idempotent at the charger (CLAUDE.md). Adding retry logic there would be
wrong. What did change is the log: a refusal used to print "auto-stop sent", which is exactly
the line someone greps when a session will not stop. The wallet path also counts a refusal as
`SessionAutoStopFailed`, since a session running past its cap is what ends in a negative
derived balance. `_dispatch_remote_stop` now warns distinctly when the charger refuses, since
that means the records say STOPPED while the hardware may still be energised.

**Tests.** `TestBackwardCompatibility` deleted rather than ported — its three tests asserted
that `success, response = outcome` kept working, which was only ever true during the
migration. Replaced with `TestTheTupleShapeIsGone`, carrying a tombstone recording where each
intent went, and inverting the central one: unpacking must now raise. Mocks in
`test_chargers.py` and `test_socket_charger.py` returned raw tuples and were updated to
`CommandOutcome`.

**Full suite, per-file per CLAUDE.md: 798 passed, 0 failed.** The 6 documented cross-loop
flakes in `test_integration.py` / `test_post_boot_state.py` do not reproduce under per-file
execution, consistent with the known guidance.
