# Rename tariff columns + back-calc base rate (foundation)

Status: done

## What to build

Reinterpret the operator-typed tariff as **GST-inclusive, gateway-exclusive** energy price, per ADR 0026. Rename the storage column `tariff_per_kwh_all_in → rate_gst_included` on **both** the `tariff` and `gst_invoice` tables (value unchanged — a pure rename), and recompute the retained `rate_per_kwh` as `rate_gst_included / (1 + gst_percent/100)`. The operator input, admin echo, and seed scripts move to writing `rate_gst_included` + back-calculating `rate_per_kwh`. This is the schema foundation every other slice builds on; it must land and be green before the billing-logic slices.

Migration is Aerich (follow the repo workflow: `aerich upgrade` to sync local first, rename the model fields, `aerich migrate`, accept the rename prompt if offered, splice the back-calc `UPDATE` into the generated `upgrade()`; `downgrade()` reverses the rename and restores `rate_per_kwh = rate_gst_included × 0.98/1.18`). No hand-editing of applied migrations. Delete `back_derive_rate_per_kwh` (superseded by the simple back-calc). Update the ~16 test fixtures that construct tariffs to set `rate_gst_included` (fixture rename is mechanical but wide — `conftest.py` included).

The one-time transition effect (existing tariffs' effective customer total ticks up ~2% because the gateway is now on top rather than baked in) is expected and admin-adjustable — see ADR 0026.

## Acceptance criteria

- [ ] Aerich migration renames `tariff_per_kwh_all_in → rate_gst_included` on `tariff` and `gst_invoice`; `upgrade()` recomputes `rate_per_kwh = round(rate_gst_included / (1 + gst_percent/100), 4)`; `downgrade()` reverses both cleanly
- [ ] `models.py` fields renamed on `Tariff` and `GSTInvoice`; stale column comments corrected (rate_per_kwh no longer references a gateway term)
- [ ] Admin create/edit (`routers/chargers.py`) accepts `rate_gst_included`, stores it, back-calculates `rate_per_kwh`; GET echoes `rate_gst_included`
- [ ] `seed_data.py` + `seed_docker.py` write `rate_gst_included` + back-calc
- [ ] `back_derive_rate_per_kwh` removed; no dangling imports
- [ ] All tariff-constructing fixtures updated; affected per-file pytest green (`docker exec ocpp-backend pytest`)
- [ ] Historical `gst_invoice` snapshot rows keep their original stored value under the renamed column (immutable-invoice invariant intact)

## Blocked by

- None - can start immediately

## Comments

**2026-09-01 — reconciled to `done` by tracker audit.** Still marked open long after the
work shipped; the tracker had no close ritual, so the status was never moved back.
Verified by locating the artifact this issue specifies in the live repo: all-in tariff columns present via `backend/migrations/models/38_*`

Method and caveats: `.scratch/tracker-reconciliation/REPORT.md`.
