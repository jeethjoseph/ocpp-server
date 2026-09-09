# Re-stencil the four staging labels

Status: ready-for-human

## What to build

Physical work at the IDT_Staging site. Four units carry `VOW####` stickers and need to
read `VOWS####` — `VOW0001` → `VOWS0001`, `VOW0002` → `VOWS0002`, `VOW0004` → `VOWS0004`,
`VOW0005` → `VOWS0005`.

**Digits are preserved on purpose.** A re-stencilled unit reads back to its old sticker,
so anyone working from memory or an old photograph still lands on the right charger.

This exists because staging's `VOW0001` and `VOW0002` **duplicate production's**. Both
registers mint codes that a real person reads off a real unit, and staging serves real
paying customers (~11 GST invoices/day as of 2026-08) — so a code quoted from a staging
unit must not resolve against production. The database half of that separation ships in
slice 03; this is the paint half, and until it is done the two disagree.

**Production needs none of this.** Seeding makes the register agree with the paint on day
one — that is the entire reason the backfill seeds from `name` rather than allocating in
`id` order. Bench units need none either: nobody reads a code off a bench unit.

## Acceptance criteria

- [ ] All four IDT_Staging units carry a `VOWS####` label matching their `asset_code` in the staging register.
- [ ] The integer part is unchanged on each unit.
- [ ] Completion is recorded in `## Comments` — who, when, and any unit that could not be reached.

## Blocked by

- [03 — Backfill every charger from the explicit map, then flip to NOT NULL](03-backfill-and-not-null.md) — the codes must exist in the staging register before the paint claims they do.
