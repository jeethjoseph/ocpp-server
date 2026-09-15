# Name hygiene and the display fallback contract

**Partly superseded 2026-08-27 by ADR 0028.** The UUID fallbacks are settled: a
customer surface never renders `charge_point_string_id`, so fallback families 2 and 3
are simply wrong and the **Asset Code** replaces them. The trailing-space problem is
also settled, and by construction rather than by cleanup — `asset_code` is normalised
(`upper(trim(...))`) at the schema boundary before its format CHECK, so the
`"VOW0001 "` class cannot recur. Still open: `name` trim/non-empty validation (`name`
itself stays free-form and non-unique), and the per-endpoint list of schema changes.

Status: ready-for-human
Labels: wayfinder:grilling
Assignee:
Blocked-by: (none)

## Question

`name` is nullable, unvalidated (empty string passes, staging has `"VOW0001 "`
with a trailing space), and three call-site families disagree on fallback:

1. `name or f"Charger {id}"` (users.py, public_stations.py)
2. `name or charge_point_string_id` — falls back to the UUID (qr_codes.py,
   franchisee_portal.py, ChargerCombobox.tsx)
3. raw null-propagated `name` (public QR endpoints, /charge/[id] heading)

Decide the single contract that replaces all three:

- Validation going forward: trim + non-empty on create/update? Backfill-clean the
  existing trailing-space row(s)?
- Customer-facing fallback when `name` is null: the display code alone? ("S01-C04"
  with no name is acceptable; a UUID is not.)
- Where the helper lives: `Charger.display_name` / `display_code` properties on
  the model (precedent: `User.display_name`, models.py:203) + a `charger_code`
  field added to the customer-facing API schemas — enumerate which endpoints.
- Does `station.name` join the label on any surface ("VOW0001 · IDT_Staging"), or
  is name + code always enough?

Output: the fallback contract + the list of API schema changes.
