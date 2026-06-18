# 04 — Exempt internal-role (admin/franchisee) sessions from the wallet gate

Status: ready-for-human

## Parent

`.scratch/wallet-charging-gate/issues/01-backend-flag-and-endpoint-guards.md`
(this corrects an over-reach introduced there).

## What to build

The wallet-charging gate (`WALLET_CHARGING_ENABLED=false`, ADR 0011) currently
403s **every** role on the admin remote-start endpoint, including ADMIN. But an
**Internal-role Session** (ADMIN/FRANCHISEE) is operational and decoupled from
wallets per **ADR 0004** — no debit, no budget cap, no GST invoice — so it must
never be wallet-gated.

Make the gate apply only to wallet-funded **customer** sessions: when the flag is
off, a remote start by an internal-role user proceeds normally; a regular USER is
still blocked. Reuse the existing `INTERNAL_ROLES` set (`core/roles.py`) — the
same one every other wallet layer already consults (`wallet_service`,
`wallet_session_service`, `invoice_service`). Do not introduce a new role list.

Scope is the `remote_start_charging` endpoint (`require_user_or_admin`, reachable
by ADMIN). The string-id endpoint and the top-up endpoint need no change —
`require_user()` is USER-only, so internal-role users can't reach them and the
gate is already correctly customer-scoped there.

Also record the carve-out: add one line to ADR 0011's "Decision / blast radius"
noting that internal-role sessions are exempt.

## Acceptance criteria

- [ ] With `WALLET_CHARGING_ENABLED=false`, an ADMIN remote start is **not** 403'd
      (proceeds past the gate).
- [ ] With the flag off, a regular USER remote start is still 403'd.
- [ ] With the flag on (default), behaviour is unchanged for all roles.
- [ ] Regression tests cover both the admin-not-gated and user-still-gated cases
      in `tests/test_wallet_charging_gate.py`; `docker exec ocpp-backend pytest
      tests/test_wallet_charging_gate.py` is green.
- [ ] `docker exec ocpp-backend pytest tests/test_chargers.py` shows no regression.
- [ ] ADR 0011 notes the internal-role exemption.

## Blocked by

None — can start immediately (issue 01 is already committed).

## Comments

### Implemented (awaiting review/merge)

- **Fix**: `routers/chargers.py` `remote_start_charging` — guard now
  `if not wallet_charging_enabled() and user.role not in INTERNAL_ROLES`, reusing
  `core.roles.INTERNAL_ROLES` (import added). String-id + top-up endpoints
  unchanged (USER-only / N/A).
- **Tests**: `tests/test_wallet_charging_gate.py` — `test_admin_remote_start_not_gated_when_disabled`
  (flips FAIL→PASS) + `test_user_remote_start_charging_still_gated_when_disabled`.
- **Docs**: ADR 0011 blast-radius now records the internal-role exemption.
- **Verification**: `pytest tests/test_wallet_charging_gate.py tests/test_chargers.py`
  → **37 passed**, no regression.

### Post-mortem

Root cause: issue 01's gate was added without applying the existing internal-role
decoupling (ADR 0004 / `INTERNAL_ROLES`), which every other wallet layer already
honours. The seam existed; it just wasn't used. **Prevention:** any new
guard/gate on a charging-session entry point must check ADR 0004 and exempt
`INTERNAL_ROLES`. Not an architectural gap — no refactor needed.

### Deploy

Backend-only → restart picks it up (no rebuild). On staging (flag already
`false`) this immediately unblocks admin charging on `e69ca119-…`.
