# Upsert-race hardening

## Origin

Production incident (2026-07-03): `tortoise.exceptions.MultipleObjectsReturned: Multiple objects returned for "Tariff"` raised from the admin charger-update endpoint (`update_charger` → `Tariff.update_or_create`).

## Root cause

A non-atomic get-or-create with **no backing DB unique constraint**. `update_or_create` runs `SELECT … FOR UPDATE` then `INSERT`; `FOR UPDATE` cannot lock a not-yet-existing row, so two concurrent first-time writes both miss the existence check and both insert. Confirmed by the prod log: two concurrent `PUT /api/admin/chargers/38` (a double-submit) inserted two identical `tariff` rows ~2 ms apart. Every later edit of charger 38 then hit `MultipleObjectsReturned`.

## Codebase sweep

Full scan of `main.py`, `routers/`, `services/` found **exactly two** sites of this class where the lookup key has no covering unique constraint:

1. `Tariff.update_or_create(charger_id=…)` — the confirmed bug. One-tariff-per-charger **is** the domain invariant → fix with a DB constraint.
2. `VehicleProfile.get_or_create(user=…)` in the OCPP StartTransaction handler — latent (no duplicate data yet in either env). But `user → vehicles` is intentionally one-to-**many**, so a constraint would be wrong. The placeholder profile is write-only, all-`Unknown` data that nothing reads → fix by dropping it (leave `Transaction.vehicle` null).

Every other upsert/check-then-create in the codebase is already protected by a `unique` / `unique_together` / `OneToOneField`, or a `SELECT … FOR UPDATE` lock on the parent row.

## Issues

- `issues/01-tariff-unique-charger-constraint.md` — dedup + `UNIQUE(charger_id)` + race-safe upsert (AFK)
- `issues/02-drop-placeholder-vehicle-profile.md` — stop auto-creating the `Unknown` vehicle profile (AFK)

Both independent, `ready-for-agent`.
