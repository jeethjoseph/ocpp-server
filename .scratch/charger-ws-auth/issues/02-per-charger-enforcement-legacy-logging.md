# 02 — Per-charger enforcement + legacy-mode burn-down logging

Status: ready-for-agent

## What to build

Make auth enforcement per-charger and observable during migration, per ADR 0020, so the fleet can be provisioned unit-by-unit without a flag-day outage.

- Enforcement is keyed on `auth_key_hash` presence:
  - **null** ⇒ legacy mode: the connection is allowed (as today), but emits a `charger.connection_insecure` signal.
  - **non-null** ⇒ enforced (the check from slice 01 applies).
- Emit `charger.connection_insecure` as an audit event + metric on every null-hash connect, so ops can watch the insecure-charger count trend toward zero. This is the burn-down signal that gates flipping the global flag later (slice 04).
- Emit `charger.connection_rejected` with `reason=auth_failed` (reusing the existing rejected-event + `record_websocket_rejected` shapes) when an enforced charger fails auth.

## Acceptance criteria

- [ ] Chargers with a null `auth_key_hash` still connect (legacy mode)
- [ ] Every null-hash connect emits a `charger.connection_insecure` audit event + metric
- [ ] Auth failures on enforced chargers emit `charger.connection_rejected` with `reason=auth_failed`
- [ ] Enforced (non-null) chargers behave exactly as slice 01 specifies
- [ ] Per-file pytest covers legacy-allow, insecure-signal emission, and enforced-reject paths

## Blocked by

- 01 — Basic Auth check on the WS handshake
