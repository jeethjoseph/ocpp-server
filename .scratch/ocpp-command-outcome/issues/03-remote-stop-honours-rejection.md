# RemoteStop honours a charger's rejection

Status: done

## What to build

**The most consequential instance of this bug.** Three stop paths — admin, customer app
and franchisee portal — send `RemoteStopTransaction` and report success as soon as the
charger replies, without reading `status`. If the charger refuses, the operator is told
the session stopped. It has not. The session keeps running and keeps billing.

The billing-path stop (`routers/transactions.py`) already checks the verdict correctly;
these three do not. Bring them in line.

Note that a stop is not symmetric with a start: after a failed start nothing is
running, but after a failed stop a live session continues to accrue cost against
someone. Whatever the endpoint returns, the caller must be left in no doubt that the
session is still active.

## Acceptance criteria

- [ ] A `Rejected` stop produces a failure response on all three paths — admin, customer app, franchisee portal.
- [ ] The response makes clear the session is still running, so the operator knows to act again.
- [ ] "Charger declined" and "charger did not answer" are distinguishable, consistent with the start endpoints.
- [ ] The billing-path stop is unchanged — it is already correct.
- [ ] Tests cover a rejected stop on each of the three paths, asserting the response is not a success.

## Blocked by

- `01-distinguish-answered-from-accepted.md`

## Comments

**2026-09-04 — done.** All three stop paths now act on the charger's verdict:
a refusal returns **409** with copy that says the session is still running, and an
unanswered command returns **504**. The franchisee path previously returned **500** on
no-answer, reporting an offline charger as a server fault and sending expected
operational noise to Sentry.

**Correction to this ticket's own premise.** It claimed the billing-path stop in
`routers/transactions.py` "already checks the verdict correctly". It does not — it only
logs on `not success`. The earlier audit produced a false positive by matching
`transaction_status` nearby. It is left unchanged deliberately: it is documented
best-effort, used by admin force-stop, which marks the record STOPPED server-side
regardless. Worth revisiting on its own terms, since a refusal there means the books say
stopped while the hardware keeps charging — captured in issue 04's scope.

**Frontend was in scope after all.** The stop mutations branched on `includes("409")`
and showed "Charger not connected or no active session" — flatly wrong for a refusal,
where the charger *is* connected and the session *does* exist. Added `serverDetail()` to
the API client so the UI surfaces the server's own wording; no status code can express
"the session is still running".

**A mock was lying.** `test_remote_stop_charging` stubbed a bare `(True, {...})` tuple,
which unpacks fine but has no `is_refused`, so it failed the moment the handler asked a
real question. Fixed the fixture rather than weakening the code, and updated the
remote-start mock the same way so issue 02 does not trip over it.

Verified: 5 new tests in `tests/test_remote_stop_outcome.py` (admin + customer app,
refused and unanswered, plus one asserting the transaction stays RUNNING after a
refusal), 2 in `test_franchisee_portal.py`, and **204 tests green** across the nine
affected files. Frontend `npm run build` and `npm run lint` both pass (0 errors).
