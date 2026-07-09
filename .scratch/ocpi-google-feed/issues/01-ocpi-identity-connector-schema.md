# OCPI identity + connector schema (Aerich migration + backfill)

Status: ready-for-agent

## What to build

Add the persisted, frozen OCPI identity columns and the structured connector columns required by the feed, via a single **Aerich-generated** migration with a backfill. No feed/UI yet — this is the schema foundation everything else builds on.

**`Charger`:**
- `ocpi_evse_id` — nullable, **unique** VARCHAR. eMI3 format `IN*{OCPI_PARTY_ID}*E{Charger.id}`. Assigned once at creation, **never recomputed**.
- `publish_to_google` — boolean, **default `false`**.

**`ChargingStation`:**
- `ocpi_location_id` — nullable, **unique** VARCHAR. Value `str(ChargingStation.id)`, frozen at creation.

**`Connector`** (per [ADR 0016](../../../docs/adr/0016-connector-ocpi-normalization.md)):
- `ocpi_standard` (enum: `IEC_62196_T2`, `IEC_62196_T2_COMBO`, `CHADEMO`, `DOMESTIC_B`, …) — nullable
- `ocpi_format` (enum: `SOCKET`, `CABLE`) — nullable
- `ocpi_power_type` (enum: `AC_1_PHASE`, `AC_3_PHASE`, `DC`) — nullable
- `max_voltage` (int, volts) — nullable
- `max_amperage` (int, amps) — nullable
- `connector_type` is retained unchanged as **display-only** (do not drop).

**Backfill (in the migration):**
- Existing `Charger` rows → `ocpi_evse_id = IN*{party}*E{id}` using the env's `OCPI_PARTY_ID` (`VLT` prod / `VLS` staging — note the stored value bakes in the env's party at backfill time).
- Existing `ChargingStation` rows → `ocpi_location_id = str(id)`.
- Best-effort connector auto-mapper: fill unambiguous rows (`Type2` → `IEC_62196_T2`/`SOCKET`, `CCS`/`CCS2` → `IEC_62196_T2_COMBO`/`CABLE`/`DC`, etc.); ambiguous/unknown rows stay **NULL** for later admin classification. `publish_to_google` is left `false` for all rows.

See [ADR 0015](../../../docs/adr/0015-ocpi-identity-scheme.md) for the identity rationale (why int `Charger.id` not `charge_point_string_id`, why frozen, hardware-swap procedure) and [CONTEXT.md](../../../CONTEXT.md).

## Acceptance criteria

- [ ] Migration generated with **Aerich** (`docker exec ocpp-backend aerich migrate`), not hand-written. If Aerich refuses, stop and follow the stale-local-DB / snapshot recovery procedure rather than hand-editing.
- [ ] `Charger.ocpi_evse_id` and `ChargingStation.ocpi_location_id` are unique + nullable; `Charger.publish_to_google` is non-null default `false`.
- [ ] New `Charger`/`ChargingStation` rows get their OCPI id auto-assigned once at creation from the derived default and never recomputed on later saves (model-level default or creation hook + test).
- [ ] Five connector OCPI columns exist with the documented enums; `connector_type` is unchanged.
- [ ] Backfill populated `ocpi_evse_id`/`ocpi_location_id` for all existing rows using the running env's `OCPI_PARTY_ID`; unambiguous connectors auto-mapped, ambiguous left NULL.
- [ ] `aerich upgrade` then `aerich downgrade` round-trips cleanly on a fresh DB.
- [ ] Tests assert id format, uniqueness, freeze-on-recompute, and auto-mapper coverage (mapped vs left-NULL cases).
- [ ] Affected backend test files pass per-file (excluding the documented baseline flake in CLAUDE.md).

## Blocked by

None — can start immediately.
