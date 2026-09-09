# Confirm the eight production stencils

Status: ready-for-human
Assignee: jeethjoseph

## What to build

Nothing — this is a confirmation, and it is the only human judgement in the effort.

Slice 03 seeds each production charger's Asset Code from the `VOW####` stencil recorded
in `Charger.name`. That is the single exception to the code being unrelated to `name`,
and it exists so the paint already on the fleet stays valid. The assumption underneath
it is that `name` faithfully records the sticker on the unit — and that assumption is
weaker than it looks. `name` has **no write-side validation anywhere**: no trim, no
format check, no non-empty check, on neither create nor update. It has demonstrably
drifted (five of production's thirteen rows hold non-stencil text). And nothing
corroborates it — only one production row carries a `serial_number`.

So the risk is not hypothetical drift, it is *unmeasured* drift on the eight rows that
matter. If one has drifted, seeding binds a wrong code to a unit permanently, and a
customer quoting `VOW0006` resolves to a different charger at the same station. That is
a wrong-answer bug, not a missing-answer one — the same failure that made us reject
pure `id`-order allocation, arriving by a different route.

Confirm that the label on each of production's eight fleet units matches `Charger.name`
as listed in `../asset-code-assignments.csv`. Four sites: IDofThings (`VOW0001`,
`VOW0002`), Seleno Stones (`VOW0003`), SARADHY TOWERS (`VOW0006`, `VOW0007`), SK EV
Charging Station (`VOW0008`–`VOW0010`). Bench units need no check — they carry no
stencil and their codes are allocated, not seeded.

**The requirement is confirmation, not a particular medium.** The CSV cannot be its own
evidence: it is generated from `name`, so checking it against `name` is circular. Anyone
who knows the fleet can sign off the eight rows from memory; photographs are only the
fallback when nobody is confident, and then they are just the record.

**This gates slice 04, not slice 03.** The code becomes permanent when it starts landing
on GST Invoices, which is 04. Between 03 and 04 it lives only in the database and on
admin surfaces, where a wrong value is an `UPDATE`, not a scar. So 01, 02, 03 and 05 all
proceed while this is outstanding — and **05 is the natural way to do it**: once the
admin UI shows the code, someone at a site compares the charger detail page to the label
in front of them during normal work, rather than making a special errand of it.

**Prior probability is good.** Production holds 1, 2, 3, 6, 7, 8, 9, 10 and staging holds
1, 2, 4, 5; the union covers 1–10 with only staging's two clones duplicated, and the
production gaps at 4 and 5 are explained by those units living at the staging site. That
is what a maintained register looks like. `name` is very likely accurate — it is merely
unvalidated, so "very likely" is the strongest claim available without looking.

## Acceptance criteria

- [ ] All eight production fleet rows in `../asset-code-assignments.csv` are confirmed against the physical label, by someone who has actually seen or reliably knows each unit.
- [ ] The confirmation is recorded in this ticket's `## Comments` section — who confirmed, when, and by what means (from knowledge / on site / photograph).
- [ ] Any mismatch is recorded explicitly, naming the row and both values (what the label says, what `name` says).
- [ ] **All eight clean** ⇒ the seed in slice 03 stands and production is never re-stencilled. Say so in the comment, so slice 04 has an unambiguous green light.
- [ ] **Any mismatch** ⇒ either correct that single row before slice 04 lands, or — if the register turns out broadly untrustworthy — escalate to restarting production at `VOW1001` and re-stencilling all twelve, so no new code can alias an old sticker. That is a decision on the evidence, not a default.

## Blocked by

None — can start immediately, and is deliberately asynchronous. Do not let it hold up 01, 02, 03 or 05.
