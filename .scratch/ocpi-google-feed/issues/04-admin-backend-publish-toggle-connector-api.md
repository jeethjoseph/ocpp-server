# Admin backend: `publish_to_google` toggle (completeness gate + audit log) + connector OCPI write API

Status: ready-for-agent

## What to build

Backend endpoints for admins to (a) flip a charger's `publish_to_google` flag under a hard completeness gate with an audit trail, and (b) set the structured connector OCPI fields so chargers can become feed-eligible.

**Publish toggle:**
- Endpoint (admin-only, `require_admin`) to set `publish_to_google` true/false on a `Charger`.
- **Completeness gate** — hard block flipping to `true` unless ALL hold (per [ADR 0015](../../../docs/adr/0015-ocpi-identity-scheme.md)): `ocpi_evse_id` assigned; the station has coords + city + address; the connector has `ocpi_standard` (and the other required OCPI fields). Return a structured error listing exactly which fields are missing.
- **Audit-logged** — every flip (both directions) writes an audit-log entry (actor, charger, old→new, timestamp). Publishing has irreversible-in-identity side effects; the audit trail is mandatory.
- Un-flagging to `false` is allowed without the gate (visibility removal), but is still audit-logged; the `ocpi_evse_id` remains permanently spent and must never be rebound.

**Connector OCPI write API:**
- Extend the connector create/edit endpoint(s) to accept and validate `ocpi_standard`, `ocpi_format`, `ocpi_power_type`, `max_voltage`, `max_amperage` (reject out-of-enum values). New connectors should be OCPI-clean by construction.

See [ADR 0016](../../../docs/adr/0016-connector-ocpi-normalization.md) and the audit-log precedent already used by `change_charger_availability`.

## Acceptance criteria

- [ ] Flipping `publish_to_google` to `true` succeeds only when the completeness gate passes; otherwise returns a structured error naming the missing fields (no partial publish).
- [ ] Every flip (true→false and false→true) writes an audit-log entry with actor + old/new value.
- [ ] Un-flagging to `false` is permitted regardless of completeness and is audit-logged.
- [ ] Connector create/edit accepts and validates the five OCPI fields; invalid enum values are rejected with a clear error.
- [ ] Endpoints are admin-gated (`require_admin`); franchisee-portal exposure (if any) follows the same gate.
- [ ] Tests cover: gate pass/fail per missing field, audit entries on both directions, connector field validation accept/reject.

## Blocked by

- 01 (needs `publish_to_google` + `ocpi_evse_id` + connector OCPI columns)
