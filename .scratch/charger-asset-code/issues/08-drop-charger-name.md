# Drop `Charger.name`

Status: needs-triage

> **DEFERRED. Do not start.** This ticket exists so the decision is on the record, not
> so it can be grabbed. Four entry conditions below must all hold first, and none holds
> today. Re-triage it when they do.

## What to build

The contract half of an expand/contract, following the pattern and the reasoning of
`.scratch/diagnostic-bundle-headerless/issues/09`. Slice 04 stops `name` being
load-bearing; this removes it.

**Deliberately separate and deliberately later.** Dropping it alongside slice 03 would
destroy the only record of the fleet's painted numbers — which is simultaneously the
backfill's seed and slice 00's evidence — with no way back if the Asset Code
underperforms in the field. This effort has already been wrong twice about what it could
rely on. The column costs nothing to keep for a release.

**This reverses a charter decision.** The 2026-07-31 grilling explicitly chose "keep
`name` free-form for easy identification; add a NEW synthetic unique display code for
correctness". Reversing it is defensible once the code has proven it can carry recognition
on its own — but it *is* a reversal, and it should be recorded as one rather than slipped
in as tidy-up.

## Entry conditions — do not start until all four hold

1. Slices 04 and 05 are live in **both** environments through at least one full billing
   cycle, with GST invoices issued carrying an Asset Code.
2. Support has resolved at least one customer-quoted code end to end.
3. No code references `Charger.name` outside migrations and ADRs — **19 backend render
   sites** and **19 frontend files** at last count.
4. Anything `name` legitimately carried has been moved first. `V3C_Test`, `V7C_Test` and
   `Chargemode_1` are **hardware type** and belong in `Charger.model` / `Charger.vendor`,
   which already exist. Capture before dropping. Provenance notes like `Staging_VOW0004`
   are noise and are allowed to be lost.

## Acceptance criteria

- [ ] All four entry conditions are verified and recorded in `## Comments` before any code is written.
- [ ] Hardware-type values are moved to `Charger.model` / `Charger.vendor` in a **prior, separate** migration — not folded into the drop.
- [ ] No reference to `Charger.name` remains outside migrations and ADRs.
- [ ] The drop migration is **Aerich-generated**. Never hand-edit a past migration to remove the column — the `aerich.content` snapshot stays poisoned and every future `aerich migrate` re-emits the cleanup as an unrelated ALTER.
- [ ] The charter reversal is recorded in ADR 0028 (or a short successor ADR), naming what changed and why it became defensible.
- [ ] `docker exec ocpp-backend pytest` passes for the affected test files.
- [ ] `cd frontend && npm run build` **and** `npm run lint` both pass.

## Blocked by

- [04 — Customer surfaces render the Asset Code](04-customer-surfaces-render-the-code.md)
- [05 — Support can resolve a customer-quoted Asset Code](05-support-lookup.md)
- Plus the four entry conditions above, which are time-and-evidence gates rather than tickets.
