# Support can resolve a customer-quoted Asset Code

Status: done

## What to build

A customer reads `VOW0001` off a unit and quotes it. Support types it in and lands on the
charger. Without this, slice 04 has given customers an identifier that nobody internally
can resolve.

Admin and franchisee surfaces display the Asset Code alongside the existing identifiers,
and charger search matches on it.

**Lookup parses the integer, it does not match the string.** `VOW0001`, `VOW00001` and
`vow1` all resolve to the same unit. A foreign series is **rejected, not coerced** — a
staging code typed into production must return nothing, not silently find production's
unit with the same number. That distinction matters because both registers mint codes a
real person reads off a real unit, and both serve real paying customers.

Parsing the integer is also what makes the minimum-width rule from ADR 0028 safe: a code
typed at one padding resolves at any other, so the register can widen past `VOW9999` with
no re-padding and no re-stencil.

This slice is also **how slice 00 gets done in practice**. Once the admin UI shows the
code, someone standing at a site compares the charger detail page against the label in
front of them during normal work, rather than making a special errand of it. Worth saying
out loud to whoever picks this up.

## Acceptance criteria

- [ ] The Asset Code is visible on the admin charger list and detail pages, and on the equivalent franchisee surfaces.
- [ ] Charger search matches on the Asset Code.
- [ ] `VOW0001`, `VOW00001`, `vow1` and `VOW1` all resolve to the same charger. A test covers the padding variants explicitly.
- [ ] A foreign-series code returns no result rather than resolving to the same integer in the local series. A test covers this — it is the cross-environment hazard, not a nicety.
- [ ] A `TEST` charger shows a `TEST` badge beside its code, so bench units are obvious on admin surfaces.
- [ ] `docker exec ocpp-backend pytest` passes for the affected test files.
- [ ] `cd frontend && npm run build` **and** `npm run lint` both pass.

## Blocked by

- [03 — Backfill every charger from the explicit map, then flip to NOT NULL](03-backfill-and-not-null.md)
