Status: done

# Harden the bulk firmware deploy endpoint (skipped bucket + in-flight/same-version safety)

## What to build

The bulk firmware **deployment** endpoint currently blind-UPSERTs a PENDING `FirmwareUpdate` row for every charger id it's handed, resetting attempt/retry state unconditionally. That makes it a footgun: it can re-flash a charger already on the target version, and it can clobber an **in-flight firmware update** (a PENDING row that has already dispatched at least one `UpdateFirmware`) by resetting it to attempt 0 mid-download.

Make bulk deploy idempotent and safe to re-run by classifying each charger into one of three buckets and returning all three:

- **`skipped`** — charger is already on the target firmware version, OR has an **in-flight firmware update** (PENDING with `attempt_count > 0`). In-flight rows are left **completely untouched** — no reset of `status`, `attempt_count`, `last_attempt_at`, or `next_retry_at`. Each skipped entry carries a human-readable reason (e.g. "already on 1.5.0", "in-flight, attempt 3/5").
- **`success`** — a fresh PENDING row was created, or an existing row in a re-deployable state (PENDING with `attempt_count == 0`, INSTALLED, FAILED, or CANCELLED) was reset to a fresh PENDING.
- **`failed`** — charger not found or a genuine error. Reason included.

Net effect: re-running the same bulk deploy is a no-op for chargers already handled or actively rolling out, and never disturbs an active rollout. Force-restarting a stuck in-flight charger remains the single-charger path's job (or mark-failed → re-deploy), not bulk.

This codifies the **In-flight firmware update** definition now in `CONTEXT.md`: the `attempt_count > 0` line is what separates "scheduled" (safe to re-UPSERT) from "in-flight" (hands off).

## Acceptance criteria

- [ ] The bulk deploy endpoint returns three buckets: `success`, `skipped`, `failed` (the response model gains `skipped`)
- [ ] A charger already on the target firmware version is placed in `skipped` with reason "already on <version>" — no row mutation
- [ ] A charger with a PENDING row and `attempt_count > 0` is placed in `skipped` with reason naming the attempt (e.g. "in-flight, attempt 3/5") — its `status`/`attempt_count`/`last_attempt_at`/`next_retry_at` are byte-for-byte unchanged after the call
- [ ] A charger with a PENDING `attempt_count == 0` row, or an INSTALLED / FAILED / CANCELLED row, is reset to a fresh PENDING and placed in `success`
- [ ] A non-existent charger id is placed in `failed` with a reason
- [ ] Re-running the identical bulk deploy a second time mutates nothing (all chargers land in `skipped`)
- [ ] The audit log entry reflects scheduled vs skipped vs failed counts
- [ ] Tests cover every bucket including the byte-for-byte in-flight non-mutation guard; `docker exec ocpp-backend pytest` passes for the affected firmware test files (baseline: the 6 known `gst_rate_percent` flakes per CLAUDE.md)

## Blocked by

None - can start immediately.
