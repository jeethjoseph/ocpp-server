# Connector metadata normalized to OCPI-native columns; `connector_type` retained as display only

**Status:** accepted (2026-06-24)

## Context

The OCPI 2.2.1 `Connector` object (which our direct CPO feed must emit — see [[adr-0015-ocpi-identity-scheme]]) has five mandatory fields: `standard`, `format`, `power_type`, `max_voltage`, `max_amperage`. Our `Connector` table stored only a **free-text `connector_type`** (values vary across the fleet — `Type2`, `Socket`, `CCS`, and inconsistent variants) plus a nullable `max_power_kw`. None of the five OCPI fields could be derived reliably:

- `standard`/`format`/`power_type` would require a render-time mapping over the unreliable free-text — every unmapped variant would silently drop a charger from the feed.
- `max_voltage`/`max_amperage` were not stored at all (only power).
- `power_type` (`AC_1_PHASE` vs `AC_3_PHASE`) is genuinely ambiguous from power alone.

## Decision

Add five **structured, validated** columns to `Connector` and make them the **source of truth for the feed**:

- `ocpi_standard` (enum: `IEC_62196_T2`, `IEC_62196_T2_COMBO` = CCS2, `CHADEMO`, `DOMESTIC_B`, …)
- `ocpi_format` (enum: `SOCKET`, `CABLE`)
- `ocpi_power_type` (enum: `AC_1_PHASE`, `AC_3_PHASE`, `DC`)
- `max_voltage` (int, volts)
- `max_amperage` (int, amps)

`max_power_kw` is retained (→ OCPI `max_electric_power`). The legacy **`connector_type` free-text is kept as a display-only label** (rendered by the public station map + admin UI); it is no longer authoritative for anything machine-read. The admin connector create/edit UI gains the structured enum fields, so new connectors are OCPI-clean by construction.

**Feed gating:** a connector with `ocpi_standard IS NULL` is excluded from the feed and flagged for admin classification — the same exclude-and-warn doctrine used for incomplete stations. We never emit a guessed `standard`.

**Backfill:** an Aerich migration adds the columns nullable; a best-effort auto-mapper fills the unambiguous rows (`Type2`/`CCS`); ambiguous rows stay NULL until an admin resolves them.

## Considered options

- **Render-time mapping table over `connector_type`.** Rejected: the free-text vocabulary is inconsistent, so the mapping is perpetual whack-a-mole and unmapped values silently drop chargers. Storing normalized truth converts an unbounded free-text problem into a bounded, validated one — the same rationale as the two-field charger state model in [[adr-0008-charger-availability-separate-from-status]].
- **Drop `connector_type` entirely, derive display from `ocpi_standard`.** Rejected for now: cleaner long-term but churns the public-map and admin UI for no feed benefit. Deferred.
- **Derive nominal `max_voltage`/`max_amperage` from power + a standard profile.** Rejected once we chose to store structured truth: the derived values were spec-valid but approximate; explicit columns remove the guess.

## Consequences

- Two connector-type fields now coexist (`connector_type` display, `ocpi_standard` authoritative). A future reader must know `connector_type` is cosmetic — hence this ADR. The eventual cleanup is the rejected "drop `connector_type`" option above.
- Existing connectors do not appear in the feed until their `ocpi_standard` is set — launch coverage depends on completing the backfill/classification, surfaced by the exclusion warnings.
