# Promote `INTERNAL_ROLES` to a shared `core/roles.py`

Status: ready-for-agent

## What to build

`INTERNAL_ROLES = {UserRoleEnum.ADMIN, UserRoleEnum.FRANCHISEE}` lives in `services/invoice_service.py` today. The follow-on internal-role-wallet-skip work (issues 02 + 03 in this batch) needs the same set imported by both wallet services and the Clerk webhook handler — none of which should reach into `invoice_service` for an unrelated reason.

Pure refactor, no behavior change.

### Plan

- New module `backend/core/roles.py` exporting `INTERNAL_ROLES`. Single source of truth for "which roles are operational, not customer-facing."
- `services/invoice_service.py` drops its local definition and imports from the new location.
- No call-site changes; the set's identity is unchanged for callers.

See [ADR 0004](../../../docs/adr/0004-internal-role-sessions-are-operational.md) for the broader motivation.

## Acceptance criteria

- [ ] `backend/core/roles.py` exists and exports `INTERNAL_ROLES`.
- [ ] `services/invoice_service.py` imports from the new module; no local `INTERNAL_ROLES` definition remains there.
- [ ] `grep -rn "INTERNAL_ROLES = " backend/ --include="*.py"` returns exactly one definition.
- [ ] Full backend test suite passes — no behavior change expected.

## Blocked by

None — can start immediately.
