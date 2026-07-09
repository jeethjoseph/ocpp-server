# 04 — Global REQUIRE_CHARGER_AUTH flag closes the window

Status: ready-for-agent

## What to build

A global switch that ends the migration window by rejecting even null-hash chargers, per ADR 0020. Flipped once the `charger.connection_insecure` burn-down (slice 02) reaches zero fleet-wide.

- Add a `REQUIRE_CHARGER_AUTH` env flag. When enabled, a charger with a null `auth_key_hash` is rejected at the handshake (close 1008) instead of being allowed in legacy mode.
- Thread the var through **all three compose files' `backend.environment:` blocks** (dev/staging/prod) plus the `.env*.example` files, per the project's env-var contract — updating the example files alone is not enough for the container to see it.
- Log a startup warning if `REQUIRE_CHARGER_AUTH` is enabled while chargers with null `auth_key_hash` still exist (so a premature flip fails loud rather than silently locking out un-provisioned units).

## Acceptance criteria

- [ ] `REQUIRE_CHARGER_AUTH` disabled (default) preserves legacy-mode behavior from slice 02
- [ ] `REQUIRE_CHARGER_AUTH` enabled rejects null-hash chargers with close code 1008
- [ ] Var is present in `backend.environment:` of `docker-compose.yml`, `docker-compose.staging.yml`, and `docker-compose.prod.yml`, plus the three `.env*.example` files
- [ ] Startup logs a warning when the flag is on while null-hash chargers remain
- [ ] Per-file pytest covers flag-off (legacy allowed) and flag-on (null-hash rejected)

## Blocked by

- 02 — Per-charger enforcement + legacy-mode burn-down logging
