# 03 — Admin provisioning + rotation endpoint (reveal-once)

Status: ready-for-agent

## What to build

An admin capability to generate and rotate a charger's Auth Key, per ADR 0020. Physical delivery of the key onto the unit is out of scope — charger-side change-config tooling handles that; the server only generates, hashes, stores, and reveals the plaintext once.

- An admin action that generates a 20-byte random key, stores its SHA-256 in `Charger.auth_key_hash`, and returns the **plaintext exactly once** in the response (never retrievable again).
- Rotation is the same path applied to a charger that already has a hash (provision-from-non-null): the old hash is overwritten, no grace overlap. The charger is briefly unauthenticated between rotate and re-load and fails closed until the new key is loaded.
- Audit-log the action: `charger.auth_provisioned` on first set, `charger.auth_rotated` on replace (who did it, which charger), mirroring the existing charger-admin audit pattern.
- Minimal admin UI affordance to trigger provision/rotate and display the revealed plaintext once, consistent with existing charger admin screens.

## Acceptance criteria

- [ ] Admin-only endpoint generates a 20-byte key, stores SHA-256 in `auth_key_hash`, returns plaintext once
- [ ] The plaintext is never returned again on subsequent reads
- [ ] Rotation overwrites an existing hash and emits `charger.auth_rotated`; first set emits `charger.auth_provisioned`
- [ ] A charger provisioned via this endpoint then authenticates successfully using the revealed key (end-to-end with slice 01)
- [ ] Admin UI can trigger provision/rotate and shows the one-time plaintext
- [ ] Per-file pytest for key generation, hash storage, reveal-once, and rotation-overwrite
- [ ] `cd frontend && npm run build` passes

## Blocked by

- 01 — Basic Auth check on the WS handshake
