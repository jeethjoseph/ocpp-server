# 01 — Fix socket-charger classification + make connector_type admin-editable

Status: ready-for-agent

## What to build

Socket-vs-tethered classification decides whether an admin/customer can remote-start a charger from `Available` (socket) or must wait for `Preparing` (tethered). Today it is both **too narrow** and **not editable**, so a genuinely socket charger silently shows "Cannot start - status is Available".

Two coupled problems, both to be fixed:

**A. `isSocketCharger` is an exact-literal match.** It returns true only when a connector's `connector_type.toLowerCase() === "socket"`. Real untethered connectors are almost never typed the literal `"socket"` — in the current fleet the connector-type distribution is **Type2 = 400, CCS = 9, Socket = 1**, so the classifier recognizes **1 of 410** connectors as socket, despite `Type2` (IEC 62196-2) being the standard untethered AC socket. Replace the literal match with a taxonomy that maps connector types to socket (untethered) vs tethered:
- **Socket / untethered** (startable from `Available`): `Socket`, `Type2`, `Type1`, `domestic` (case-insensitive).
- **Tethered** (require `Preparing`): `CCS`, `CHAdeMO`, `GB/T`, and any `*Cable`/`*Tethered` variant.
- Unknown types default to **tethered** (the safe default — never auto-enable start-from-Available for an unrecognized type).

**B. `connector_type` is set-once and invisible.** It is written only at charger creation; there is no connector-edit endpoint and `ChargerUpdate` doesn't include it, so the "Edit Charger" form (Name / Model / Vendor / External ID / Tariff) offers no way to correct it. An admin who wants a charger to behave as a socket has no lever — setting the free-text **Model** to "Socket" (the intuitive move) does nothing, because classification keys off `connector_type`, not `model`. Expose `connector_type` on the charger edit path (backend accepts it + persists to the connector row; frontend adds the field to the Edit Charger form, defaulting to the current value) so an admin can set it correctly.

## Acceptance criteria

- [ ] `isSocketCharger` returns true for `Type2` / `Type1` / `Socket` / `domestic` (case-insensitive) and false for `CCS` / `CHAdeMO` / `GB/T` / unknown types.
- [ ] A `Type2` charger in `Available` shows Start Charging **enabled** (given Connected + no active txn); a `CCS` charger in `Available` stays disabled with the existing "Cannot start - status is Available" hint.
- [ ] The Edit Charger form exposes `connector_type` (pre-filled with the current value); saving persists it to the connector and the Start-gating updates on refetch.
- [ ] The charger update endpoint accepts and persists `connector_type` (validated against the known type set; `model_config = extra:"forbid"` on `ChargerUpdate` still holds).
- [ ] Unit tests for the `isSocketCharger` taxonomy (socket types, tethered types, unknown-defaults-tethered, case-insensitivity).
- [ ] Backend per-file pytest for the connector_type update path; `docker exec ocpp-backend pytest` green for affected files (baseline flakes excepted per CLAUDE.md).
- [ ] `cd frontend && npm run build` passes (full production build, per project convention).

## Notes / decisions

- **Ambiguity worth flagging:** `Type2` can physically be *either* a socket or a tethered unit — connector_type alone can't always disambiguate. This issue takes the pragmatic path (treat `Type2` as socket, the dominant real-world case, and let admins correct via the now-editable field). The strictly-correct long-term model is a dedicated mounting-type field (socket|tethered) on the connector; that's a schema change + backfill and is **out of scope** here — note it as a follow-up if the `Type2` assumption proves wrong for any real unit.
- Keep the taxonomy in one shared place (the `isSocketCharger` util) so backend and frontend can't drift; if both sides need it, factor the type→category map rather than duplicating string lists.

## Blocked by

None - can start immediately.

## Comments

**2026-07-06 — implemented (backend tests pending stack restore).**
- **Taxonomy (both sides):** frontend `isSocketCharger` (`lib/utils.ts`) and backend `charger_type_service` now use a shared taxonomy — `socket`/`type1`/`type2`/`domestic` = untethered (start-from-Available); `CCS`/`CHAdeMO`/`GB-T`/unknown = tethered. Normalisation is case/space/`_`/`-`-insensitive. Backend `is_socket_connector_type` used in `is_socket_charger` + `is_socket_charger_cached` (which gate the actual remote-start endpoint), so button and backend agree.
- **Editable connector_type:** `ChargerUpdate` gains `connector_type` (validated vs `ALLOWED_CONNECTOR_TYPES`), applied to the charger's connector(s) in `update_charger`. The charger **list** now returns `connectors` (one bulk query) so the Edit form can pre-fill. Frontend Edit Charger modal adds a Connector Type `<select>` (`CONNECTOR_TYPE_OPTIONS`), pre-filled from `charger.connectors[0].connector_type`.
- **Tests:** frontend `__tests__/lib/utils.test.ts` +5 cases (vitest 17/17 green); `cd frontend && npm run build` passes. Backend `tests/test_socket_classification.py` written (taxonomy params + connector_type update persist/validate/flip + list-includes-connectors) but **not yet run** — the local dev containers are down (host disk 99% full + native redis/postgres holding 6379/5432). Backend files pass `py_compile`. Run `docker exec ocpp-backend pytest tests/test_socket_classification.py` once the stack is restored.
