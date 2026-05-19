# Transactional atomicity on charger + connector + tariff creation

Status: ready-for-agent

## What to build

**M6 — `routers/chargers.py:create_charger` performs three writes (`Charger.create`, `Connector.create` per connector input, `Tariff.create`) without a wrapping transaction.** If the tariff insert fails (DB constraint, network blip, validation), the charger persists without a tariff. If the connector loop fails halfway, the charger persists with a partial connector set.

This is a pre-existing race that the qr-billing-overhaul work didn't introduce, but the surrounding code was edited heavily — the right moment to fix it is now.

### Plan

Wrap the three-step create sequence in `async with in_transaction():`. Pattern already used elsewhere in the codebase (e.g., `qr_payment_service._full_refund` uses `in_transaction()` for the SELECT-FOR-UPDATE + write flow). If any step inside the block raises, the whole transaction rolls back and no `Charger`, `Connector`, or `Tariff` row persists.

The `log_audit_event` call should stay OUTSIDE the transaction. Rationale: audit logs are meant to capture "we attempted this" and should survive even partial failures so ops can debug. If the audit-write itself fails inside the txn, it would mask the underlying error.

Apply the same fix to `update_charger` if it does multi-row writes — investigation says it doesn't (`update_or_create` is idempotent and single-row), so leave it alone unless the investigation finds otherwise.

## Acceptance criteria

- [ ] `create_charger` wraps Charger + Connector loop + Tariff inside `async with in_transaction()`.
- [ ] Integration test: mock `Tariff.create` to raise `IntegrityError` mid-call; assert no `Charger` or `Connector` row persists for that request.
- [ ] Integration test: happy path still creates all three (regression guard).
- [ ] Audit log row IS written even when the inner transaction rolls back (the "we attempted this charger creation" audit trail is preserved).
- [ ] No regression in the existing `test_chargers.py` suite.

## Blocked by

Slice 1 (config & helper relocation) — same handler is touched by the relocation; landing them in opposite orders creates merge conflicts.
