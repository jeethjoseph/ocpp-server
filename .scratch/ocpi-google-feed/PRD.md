# OCPI 2.2.1 CPO feed — publish chargers to Google Maps

GitHub umbrella issue: [jeethjoseph/ocpp-server#72](https://github.com/jeethjoseph/ocpp-server/issues/72)

## Goal

Expose a direct **OCPI 2.2.1** CPO feed (`/ocpi/cpo/2.2/`, modules **Versions + Credentials + Locations**) so external consumers — primarily **Google Maps** via `EVCS-global@google.com` — can ingest our charging locations as POIs with **Real-Time Availability (RTA)**. Google accepts *only* OCPI for EV charging data. Tariffs module is deferred to phase 2.

Not to be confused with the consumer-facing "Get Directions → Google Maps" button on `/my-charges`, which already ships.

## Design (locked, 2026-06-24)

- [ADR 0015](../../docs/adr/0015-ocpi-identity-scheme.md) — OCPI identity scheme: env-specific `party_id` (`VLT` prod / `VLS` staging); persisted-and-frozen `Charger.ocpi_evse_id` (`IN*VLT*E{id}`) + `ChargingStation.ocpi_location_id`; per-charger `publish_to_google` flag (completeness-gated + audit-logged); both envs publish, staging as a deliberate canary.
- [ADR 0016](../../docs/adr/0016-connector-ocpi-normalization.md) — Connector normalization: five structured OCPI columns on `Connector`; `connector_type` demoted to display-only; exclude-and-warn when `ocpi_standard IS NULL`.
- [ADR 0008](../../docs/adr/0008-charger-availability-separate-from-status.md) — the two state fields (`latest_status` + `availability`) the feed fuses into OCPI EVSE status.
- [CONTEXT.md](../../CONTEXT.md) — glossary: `ocpi-feed`, `publish-to-google`.

## Slices

| # | Issue | Blocked by |
|---|-------|-----------|
| 01 | OCPI identity + connector schema (Aerich migration + backfill) | — |
| 02 | Feed scaffolding: Versions + Credentials + token auth + `OCPI_ENABLED` env wiring | — |
| 03 | Locations module: static Location/EVSE/Connector + real-time status fusion + completeness gating | 01, 02 |
| 04 | Admin backend: `publish_to_google` toggle (completeness gate + audit log) + connector OCPI write API | 01 |
| 05 | Admin frontend: publish toggle UI + structured connector enum fields | 04 |

## Out of scope (this feature)

- OCPI **Tariffs** module (phase 2).
- OCPI roaming-hub registration / registered `party_id` (revisit only if we join a hub).
- Dropping the legacy `connector_type` free-text column (deferred per ADR 0016).
