# 01 — Backend flag + endpoint guards (enforcement)

Status: ready-for-human

## Why

This is the safety-critical slice. The backend flag is the source of truth — once
this ships, no new wallet session or top-up can be created regardless of frontend
state. Shippable and valuable on its own.

## What

Introduce `WALLET_CHARGING_ENABLED` (default `true`) and enforce it server-side.

### Tasks

1. **Flag accessor.** Read `os.getenv("WALLET_CHARGING_ENABLED", "true").lower()
   == "true"` once in a small helper (e.g. in `config`/settings or a module-level
   constant), so all three call sites share one definition. Runtime-read so a
   container restart toggles it — no rebuild.
2. **Guard `remote_start_charging`** (`backend/routers/chargers.py:588`) — return
   `HTTPException(403, "Wallet charging is temporarily disabled")` when the flag
   is off, before any OCPP work.
3. **Guard `remote_start_by_string_id`** (`backend/routers/users.py:805`) — same
   403.
4. **Guard the wallet top-up order endpoint** (`backend/routers/wallet_payments.py`
   — the order-creation route) — same 403.
5. **Startup warning.** In `backend/main.py` startup event, log a clear WARNING
   when `WALLET_CHARGING_ENABLED` is false ("Wallet charging is DISABLED — see
   ADR 0011") so a misconfigured deploy is visible in logs.
6. **Compose plumbing.** Add `- WALLET_CHARGING_ENABLED=${WALLET_CHARGING_ENABLED:-true}`
   to `backend.environment:` in `docker-compose.yml`,
   `docker-compose.staging.yml`, `docker-compose.prod.yml`.
7. **Env examples.** Add to `.env.example`, `.env.staging.example`,
   `.env.prod.example` with a comment pointing to ADR 0011.

### Do NOT touch

StopTransaction billing, `wallet_service`, budget-cap auto-stop, balance reads,
or any QR path. This issue only blocks the *start* and *top-up* paths.

## Acceptance criteria

- With `WALLET_CHARGING_ENABLED=false`: both remote-start endpoints and the
  top-up endpoint return 403; an in-flight wallet session still bills correctly
  at StopTransaction; QR remote-start (if any) and QR billing unaffected.
- With the flag unset or `true`: behaviour is unchanged from today.
- `docker exec ocpp-backend env | grep WALLET_CHARGING_ENABLED` shows the value
  inside the container.
- `docker exec ocpp-backend pytest` green for affected test files (add a test
  asserting 403 when off, 200/expected when on).

## Comments

### Implemented (awaiting review/merge)

- **Shared accessor**: `wallet_charging_enabled()` in `backend/core/config.py`
  (reads `WALLET_CHARGING_ENABLED`, default `true`, at call time → restart toggles).
- **Guards (403 before any DB/OCPP work)**:
  - `routers/chargers.py` `remote_start_charging`
  - `routers/users.py` `remote_start_by_string_id`
  - `routers/wallet_payments.py` `create_recharge_order`
- **Startup log**: `main.py` startup event warns loudly when disabled (ADR 0011).
- **Compose**: `WALLET_CHARGING_ENABLED=${WALLET_CHARGING_ENABLED:-true}` added to
  `backend.environment:` in all three compose files. `docker compose config`
  confirms it renders into the backend service.
- **Env examples**: added to `.env.staging.example` + `.env.prod.example`
  (`.env.example` does not exist in this repo).
- **Tests**: `tests/test_wallet_charging_gate.py` — accessor parsing + 403-when-off
  + gate-open-when-on for all three endpoints. **10 passed.** Regression check:
  `test_chargers.py` + `test_wallet_end_to_end.py` → **26 passed**.

Not done here (correct per slice boundary): frontend UI hide (issue 02), setting
the flag `false` on staging/prod (issue 03), and the llm-context /
comprehensive-architecture doc updates (defer to feature completion).
