# A bench unit refuses to charge a customer

Status: ready-for-agent

## What to build

The last gate, and the one with revenue on the wrong side of a mistake. A `TEST` charger
rejects `StartTransaction` for any user not in `INTERNAL_ROLES` (`{ADMIN, FRANCHISEE}`),
returning the existing `Blocked` idiom. Billing and GST invoice suppression ride along:
a `TEST` charger is never billed and never invoiced, for anyone.

Place it in `main.py` immediately after the existing `user.is_active` check, and reuse
that check's shape rather than inventing a second rejection style — the OCPP response
vocabulary is fixed and the handler already knows how to say no.

**Ship this last, after slice 03 is verified in each environment.** Every other slice in
this effort fails open: a row missed by the backfill keeps working. This one fails
**closed** — a fleet unit wrongly carrying `purpose = TEST` stops accepting customers
entirely. That is a revenue outage on that unit, and it is the single place in the effort
where a wrong value in the backfill costs money rather than an `UPDATE`. Confirm the
`TEST` set is right in the target environment before deploying, not after.

## Acceptance criteria

- [ ] `StartTransaction` on a `TEST` charger returns `Blocked` for a customer.
- [ ] `StartTransaction` on a `TEST` charger succeeds for `ADMIN` and `FRANCHISEE` — bench hardware stays testable by the people who test it.
- [ ] `PUBLIC` chargers are entirely unaffected for every role.
- [ ] A session on a `TEST` charger is never billed — no wallet deduct, no QR charge.
- [ ] A session on a `TEST` charger issues no GST Invoice.
- [ ] The rejection uses the same idiom as the adjacent `user.is_active` check.
- [ ] Tests cover both the customer rejection and the internal-role allowance.
- [ ] `docker exec ocpp-backend pytest` passes for the affected test files.
- [ ] Before deploying to each environment, the `purpose = TEST` set in that register is confirmed correct. Record the check in `## Comments`.

## Blocked by

- [03 — Backfill every charger from the explicit map, then flip to NOT NULL](03-backfill-and-not-null.md)
- [06 — Bench units stop appearing on public surfaces](06-public-visibility-filter.md)
