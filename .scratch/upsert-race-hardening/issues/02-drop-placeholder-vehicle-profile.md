# 02 — Drop the auto-created placeholder VehicleProfile in StartTransaction

Status: ready-for-agent

## What to build

The OCPP StartTransaction handler auto-creates a placeholder `VehicleProfile` (`make`/`model` = `"Unknown"`) per user via a non-atomic `VehicleProfile.get_or_create(user=user)`, and links it to the new `Transaction`. Three problems:

- **It's write-only data.** Nothing in the app reads `transaction.vehicle` — no billing, invoice, export, API response, or frontend. All 114 prod profiles (and staging) are `Unknown / Unknown`.
- **It contradicts the domain model.** `user → vehicles` is intentionally one-to-**many** (plain FK, `related_name="vehicles"`; `Transaction.vehicle` is a nullable FK). A singular `get_or_create(user=user)` breaks the moment a user has two profiles — from a concurrent-StartTransaction race or a real second vehicle — raising `MultipleObjectsReturned` on **every** subsequent StartTransaction and locking that user out of charging.
- **It's a sentinel-row anti-pattern.** A nullable FK should be `null` when there's no real value, not filled with a fabricated "Unknown" row. OCPP 1.6 StartTransaction carries no vehicle identity, so `null` is the honest representation.

Stop manufacturing the placeholder. Remove the `get_or_create` from the StartTransaction handler and create the `Transaction` with `vehicle=None`. This removes the racy upsert from the hot OCPP path entirely, so the bug class disappears rather than being worked around. No DB constraint change — one-to-many stays correct.

Existing `Unknown/Unknown` rows may be left in place (harmless — nothing reads them); do **not** delete them as part of this slice.

## Acceptance criteria

- [ ] StartTransaction no longer creates a `VehicleProfile`; the new `Transaction` has `vehicle_id = NULL`.
- [ ] A user who already has 2+ `VehicleProfile` rows can StartTransaction without `MultipleObjectsReturned`.
- [ ] Nothing regresses from the null FK (verified: no code path reads `transaction.vehicle` expecting non-null today).
- [ ] Per-file pytest covers: StartTransaction succeeds and leaves `vehicle` null; a user with multiple existing profiles can start a session.
- [ ] `docker exec ocpp-backend pytest` passes for the affected test file(s) (baseline flakes excepted per CLAUDE.md).

## Notes

- Future vehicle-identity work (a user-facing "my vehicles" picker, or an RFID→vehicle mapping) is where `Transaction.vehicle` should be populated with real data. Out of scope here.

## Blocked by

None - can start immediately.

## Comments

**2026-07-03 — implemented.** Removed the `VehicleProfile.get_or_create(user=…)` from `ChargePoint.on_start_transaction` in `main.py`; the `Transaction` is now created without `vehicle` (FK left null). Dropped the now-unused `VehicleProfile` import. No migration (one-to-many stays correct); existing `Unknown/Unknown` rows left untouched. Regression tests in `tests/test_start_transaction_no_vehicle.py` (2 pass): first-time user → txn with `vehicle_id` null and zero profiles created; a user with 2 existing profiles can StartTransaction without `MultipleObjectsReturned` and no third profile is added. OCPP-flow suites green: `test_socket_charger` (20), `test_resume_staleness_guard` (11), `test_wallet_session_service` (10), `test_integration` (5).
