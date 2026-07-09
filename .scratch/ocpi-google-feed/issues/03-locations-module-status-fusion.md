# Locations module: static Location/EVSE/Connector + real-time status fusion + completeness gating

Status: ready-for-agent

## What to build

Serve the OCPI **Locations** module — the actual payload Google ingests — under `/ocpi/cpo/2.2/locations`. Emits one Location per `ChargingStation` that has ≥1 published EVSE, with real-time EVSE status (RTA, which Google requires).

**Endpoints:**
- `GET /ocpi/cpo/2.2/locations` — paginated list (OCPI pagination headers: `Link`, `X-Total-Count`, `X-Limit`).
- `GET /ocpi/cpo/2.2/locations/{location_id}` — single Location.

**Serialization:**
- **Location** ← `ChargingStation`: `id = ocpi_location_id`, `party_id`/`country_code` from config, coordinates, address, city, plus the published EVSEs.
- **EVSE** ← `Charger` with `publish_to_google = true`: `uid = charge_point_string_id`, `evse_id = ocpi_evse_id`, connectors, and **`status`** fused from the two state fields per [ADR 0008](../../../docs/adr/0008-charger-availability-separate-from-status.md):
  - `availability = Inoperative` → OCPI `INOPERATIVE` (admin command wins).
  - else map `latest_status`: `Available`→`AVAILABLE`, `Charging`→`CHARGING`, `Preparing`/`Finishing`/`SuspendedEV`/`SuspendedEVSE`→`OCCUPIED` (or `CHARGING` per closest OCPI semantics — document the mapping), `Faulted`→`OUTOFORDER`, `Reserved`→`RESERVED`, `Unavailable`→`UNAVAILABLE`.
- **Connector** ← `Connector`: `id = "1"` (one-connector-per-charger invariant), `standard`/`format`/`power_type` from the OCPI columns, `max_voltage`/`max_amperage`, `max_electric_power` from `max_power_kw`.

**Completeness gating (exclude-and-warn, per ADR 0015 + 0016):**
- A Location is emitted **iff** it has ≥1 published EVSE that passes the gate.
- An EVSE/connector missing `ocpi_evse_id`, station coords/city/address, or `ocpi_standard` is **excluded** and logged/flagged for admin classification. Never emit a guessed `standard` or a partial object.

## Acceptance criteria

- [ ] `GET /locations` returns only stations with ≥1 gated-published EVSE, with correct OCPI pagination headers.
- [ ] `GET /locations/{id}` returns the single Location or an OCPI not-found envelope.
- [ ] EVSE `status` is correctly fused: `availability=Inoperative` overrides to `INOPERATIVE`; otherwise the documented `latest_status` mapping applies (table covered by tests).
- [ ] Connector fields serialize from the OCPI columns; `connector_type` free-text is **not** used for any machine-read field.
- [ ] Incomplete chargers/connectors/stations are excluded and a warning is logged/surfaced; a station whose only EVSE is incomplete does not appear at all.
- [ ] `publish_to_google = false` chargers never appear in the feed.
- [ ] Response envelopes are OCPI-spec-shaped; served behind the issue-02 token auth + `OCPI_ENABLED` gate.
- [ ] Tests cover: status-fusion matrix, exclude-and-warn for each missing field, pagination, and the published/unpublished filter.

## Blocked by

- 01 (identity + connector columns)
- 02 (router scaffold + token auth + env gate)
