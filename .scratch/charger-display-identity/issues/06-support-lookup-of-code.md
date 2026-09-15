# Support lookup of the display code

**Re-scoped 2026-08-27 by ADR 0028.** Search is a lookup on a stored, uniquely-indexed
column — not a `LIKE`, and not a parse back to `(station, bay)` as the 2026-08-24 draft
had it. The typed string is normalised by parsing its integer part, so `VOW0001`,
`VOW00001` and `vow1` all resolve to one row and a foreign series is rejected rather
than coerced — which is also what makes the minimum-width format safe. The touchpoint list — chargers list/detail, `ChargerCombobox` secondary
line, franchisee portal — is still undecided.

Status: ready-for-human
Labels: wayfinder:grilling
Assignee:
Blocked-by: (none)

## Question

The charter names "support reference" as one of the label's jobs: a customer reads
"S01-C04" off their bill to support, and support must resolve it to exactly one
charger. Decide the minimum admin-side surfacing that makes this work:

- Where the code appears read-only in the admin UI (chargers list/detail,
  ChargerCombobox secondary line — which currently shows the UUID)?
- Is the code searchable in the admin chargers list / combobox filter?
- Does the franchisee portal show it too (franchisees field customer complaints)?

Scope guard: this is the MINIMUM for the support job, not an admin UI redesign —
anything beyond display + search goes to the map's Out of scope.

Output: list of admin/franchisee touchpoints for the spec.
