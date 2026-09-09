# Asset Code assignment worksheet (ADR 0028 backfill)

Status: ready-for-human (review, not data entry)
Assignee: jeethjoseph
Blocked-by: (none)

Replaces the bay-number worksheet from 2026-08-24. That sheet asked for a physical
survey — a human at each site reading a number off the ground that no label carried.
This one asks for a **review**, because every code is derived from data already in the
database: the `VOW####` stencil recorded in `Charger.name`.

Live data pulled 2026-08-24 via SSM (`charger` ⋈ `charging_station`). Codes computed
2026-08-27 per ADR 0028.

## Seeding rules

The Asset Code is **system-allocated and unrelated to `Charger.name`**. This backfill
is the single exception: it seeds from the stencils already painted on the fleet so
existing labels stay valid. After it runs, nothing reads `name` for identity again.

- A row whose `name` matches `^VOW\d+$` is **fleet hardware** and keeps its painted
  number: prod `VOW0003` stays `VOW0003`, staging `VOW0004` becomes `VOWS0004`.
- Every other row is **bench/test hardware**: `purpose = TEST` plus the next free code
  in its register, allocated monotonically from `max(fleet) + 1`.
- Gaps stay gaps. Production has no `VOW0004`/`VOW0005` because those two units sit at
  the staging site; they are not backfilled, and production's next new unit is `VOW0016`.

**Why seed rather than allocate in `id` order.** Pure `id`-order allocation shifts six
of production's eight painted units — the unit painted `VOW0006` would be issued
`VOW0007`, which is the sticker on a *different* charger at the same station. A customer
quoting `VOW0006` would resolve to the wrong unit: a wrong-answer bug, not a
missing-answer one. Seeding costs one `SELECT` in `upgrade()` and avoids it entirely.

## What actually needs a human

Only one column: **`purpose`**. The `TEST` classification is inferred from the name
looking like a test unit, and that inference is the only judgement in the sheet.

- A fleet unit wrongly marked `TEST` stops billing and disappears from public surfaces
  once those filters ship — a revenue outage on that unit.
- A bench unit left `PUBLIC` keeps the status quo: it stays visible on `/stations` and
  the no-auth map, as all five production test units do today. Wrong, but not a
  regression.

The failure directions are asymmetric on purpose, and `purpose` defaults to `PUBLIC`,
so a row missed entirely keeps working. Confirm the five production `TEST` rows in
particular — they sit on station 6 (IDofThings) alongside real fleet hardware.

## Why the production bench units stay (investigated 2026-09-03)

Deleting the five production `TEST` units instead of flagging them was evaluated
and rejected on evidence. Live query against the production register:

| id | name | txns | GST invoices | live Razorpay QR |
|---|---|---|---|---|
| 27 | V3C_Test | 23 — 22 ADMIN, **1 USER** | **1** | `qr_SVOI4IVF6I88vW` |
| 29 | V7C_Test | 18 — all ADMIN | 0 | `qr_SYCN1gsuNTq0HO` |
| 30 | Chargemode_1 | 0 | 0 | — |
| 36 | Staging_VOW0002 | 0 | 0 | — |
| 37 | Staging_VOW0004 | 0 | 0 | — |

**Charger 27 must never be deleted.** It carries `VL/QR/202627/00001` — issued
2026-04-24 to a `USER`-role account, ₹0.03, QR series, FY 2026-27. That is serial
**00001**, the first of the series for the financial year. `Transaction.charger`
(`models.py:408`) and `GSTInvoice.transaction` (`models.py:1030`) both omit
`on_delete`, so Tortoise's default `CASCADE` applies and deleting the charger takes
the invoice with it — a gap at the very start of a Rule 46(b) consecutive series.

**27 and 29 hold live Razorpay QR codes.** Deleting the charger row does not close
the QR on Razorpay's side (`_close_orphan_razorpay_qr` fires only when a local
insert fails, never on delete). An orphaned QR stays scannable, and the webhook
skips not-found transactions — money into the nodal balance, no session, no refund
path.

**30, 36 and 37 are genuinely clean** and could be deleted, but there is no reason
to: `purpose = TEST` reaches the same operational state reversibly, and a uniform
rule beats a per-row exception.

This is the concrete case for serviceability being a *field* rather than row
existence. Row deletion cannot express "not for customers" once a row has entered
the statutory register.

## Physical work

- **Production: none.** Seeding makes the register agree with the paint on day one.
  That is the entire return on the seeded backfill.
- **Staging: four labels, one site.** `VOW0001/0002/0004/0005` at IDT_Staging become
  `VOWS0001/0002/0004/0005`. The series gains a letter so the paint must follow; the
  digits are preserved so each unit reads back to its old sticker. Note `VOW0001` in
  the DB carries a trailing space — the seed trims it.
- **Bench units: none.** Nobody reads a code off a bench unit.

## Assignments

See `asset-code-assignments.csv` — 22 rows, 13 production and 9 staging.

| Register | Fleet (`PUBLIC`) | Bench (`TEST`) |
|---|---|---|
| production `VOW` | `VOW0001`–`VOW0010`, gapped at 4 and 5 | `VOW0011`–`VOW0015` |
| staging `VOWS` | `VOWS0001`, `0002`, `0004`, `0005` | `VOWS0006`–`VOWS0010` |
