# Charter decisions (grilling, 2026-07-31)

Status: closed
Labels: wayfinder:grilling
Assignee: jeethjoseph

## Question

What is the destination for the "customers see charger Name, but names aren't
unique" effort, and which top-level decisions frame it?

## Resolution

Grilled 2026-07-31, all answers from the map driver:

1. **Label's job** (multi-select): recognition ("which stop was this") + support
   reference (customer reads it to support, must resolve to exactly one charger) +
   compliance (the bill is a tax document; identity must be exact and auditable).
2. **Name vs code**: keep `name` free-form for easy identification; add a NEW
   synthetic unique display code for correctness. (Rejected: name-only with txn-ID
   traceability; enforced-unique names; showing the raw string ID alongside.)
3. **Code scheme**: station-prefixed, **Variant A — numeric**: `S{station_id}-C{seq}`
   (e.g. `S01-C04`), per-station sequence, auto-assigned at creation, backfilled by
   migration for existing chargers in creation order. **Immutable for the charger's
   life** — a station move does NOT regenerate the code (bills snapshot it anyway).
   (Rejected: franchisee prefix — means nothing to customers and churns; admin-typed
   free codes — invites the trailing-space class of errors already seen on staging;
   station short-codes — pushes a naming problem up to stations.)
4. **Scope**: ALL customer surfaces — GST invoice PDF, /my-charges, /my-sessions,
   /charge/[id], UPI payee/description, /stations — one shared display helper; a
   customer never sees the UUID again.
5. **GST invoice**: add `charger_name` + `charger_code` snapshot columns written at
   issuance; new invoices render name + code; keep snapshotting the UUID internally
   for audit but stop printing it; already-issued invoices stay frozen.

Supporting facts (staging, via SSM): `VOW0001`-style values are the `name` column,
not a separate code system; `charge_point_string_id` is always a UUID; the GST PDF
currently prints that UUID as "CHARGER ID"; `station` FK is non-nullable
(models.py:322) so station can anchor the prefix.
