# RemoteStart honours a charger's rejection

Status: done

## What to build

Today, if a charger refuses a remote start, both start endpoints report success. The
admin endpoint returns `200 {"success": true, "message": "Remote start command sent
successfully"}` and the customer-app endpoint returns an equivalent. Nothing plugs in,
and the operator or driver has been told it worked.

Make both endpoints act on the charger's verdict: a refusal must surface as a failure,
with a message that says the charger declined rather than implying a transport problem.

The **QR payment flow already does this correctly** and is the model to follow, not to
duplicate — it retries only communication failures, treats an explicit rejection as
terminal ("no point retrying"), and re-reads state between attempts in case the charger
started anyway and only the response was lost. That last detail exists because the
Quectel modem is known to corrupt responses; any retry added here inherits the same
hazard.

Also settle the inconsistency between the two endpoints: on a timeout the admin
endpoint returns **504** and is deliberately excluded from Sentry as expected
operational noise, while the customer-app endpoint returns **500** and therefore
reports an offline charger as a server fault. They should agree.

Decide explicitly whether these endpoints retry at all. Unlike QR there is no captured
payment to protect and a human is present to press the button again, so fail-fast is a
legitimate answer — but it should be a decision recorded here, not an omission.

## Acceptance criteria

- [ ] A charger that answers `Rejected` produces a failure response, not a success, on both start endpoints.
- [ ] The failure distinguishes "the charger declined" from "the charger did not answer" in both status code and message.
- [ ] Both endpoints agree on the timeout status code, and an offline charger does not surface as a server error in Sentry.
- [ ] The QR flow's behaviour is unchanged — it already handles this and must not regress.
- [ ] Retry policy for these endpoints is stated in this issue's Comments, whichever way it is decided.
- [ ] Tests cover accepted, rejected and no-answer for both endpoints.

## Blocked by

- `01-distinguish-answered-from-accepted.md`

## Comments

**2026-09-04 — done.** Both start endpoints now act on the charger's verdict: a refusal
returns **409**, an unanswered command **504**. The customer-app endpoint previously
returned **500** on no answer, reporting an offline charger as a server fault and
disagreeing with the admin endpoint about the identical condition — a 500 also lands in
Sentry, which 504 is deliberately excluded from. That asymmetry is now closed and pinned
by a test.

**Retry policy — decided: no retry**, as this ticket required be recorded either way.
QR retries because a payment is already captured and no human is watching, so an
unattended failure would strand money. On these endpoints a person is standing at the
charger with the button in front of them; a silent retry only delays the honest answer
and muddies which attempt actually succeeded. Fail fast and say why.

**A test's premise was wrong, not just its fixture.**
`test_remote_start_other_failure_returns_500` asserted a 500 while mocking
`(False, "Rejected")` — conflating a delivery failure with a refusal. Those are
different: a refusal means the charger *answered*, which per CONTEXT.md is an expected
outcome rather than a server fault. Rewritten as
`test_remote_start_refused_returns_409` against a genuine refusal.

**The success toast was making a promise the protocol never made.** It read "Remote
start command sent successfully. Waiting for charger to start charging..." — but an ACK
was only ever an acknowledgement. Now "Charger accepted the start command. Waiting for
charging to begin...", and both start mutations surface the server's own wording on
error via `serverDetail()`.

The QR flow is untouched. It already handled all of this correctly, and it is the one
path with money at stake.

Verified: 4 new tests in `tests/test_remote_start_outcome.py`, plus the two rewritten in
`test_chargers.py`, and **208 tests green** across ten files. Frontend `npm run build`
and `npm run lint` both clean (0 errors, 7 pre-existing warnings).
