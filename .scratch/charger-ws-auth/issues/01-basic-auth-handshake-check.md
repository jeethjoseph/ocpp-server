# 01 — Basic Auth check on the WS handshake (schema + pre-accept enforcement)

Status: ready-for-agent

## What to build

Authenticate the OCPP WebSocket connection with HTTP Basic Auth over the existing WSS transport (OCPP 1.6 Security Profile 2), per ADR 0020. This is the core end-to-end slice: after it, a provisioned charger's connection is genuinely protected against identity spoofing.

- Add a nullable `Charger.auth_key_hash` column (Aerich migration).
- In the OCPP WebSocket handshake, read the `Authorization` header **before `websocket.accept()`**. If a hash is present for the charger, verify the presented Basic Auth password against `auth_key_hash` (SHA-256), and require the Basic Auth **username to equal the `{charge_point_id}` in the URL path**.
- On failure, close the handshake with code **1008** without ever accepting the socket or creating an OCPP session.
- The auth check must run **before** the "already connected ⇒ force-disconnect the stale connection" logic, so an unauthenticated caller can never kick a live charger offline via the reject path.

Follow the SHA-256 (not bcrypt) decision and the ordering constraints in ADR 0020. Keep functions under 40 lines.

## Acceptance criteria

- [ ] `Charger.auth_key_hash` column added via Aerich migration (nullable)
- [ ] Handshake reads `Authorization` and rejects invalid/mismatched credentials with close code 1008 before `accept()`
- [ ] Basic Auth username must equal the path `charge_point_id`; mismatch is rejected even with a valid password
- [ ] Auth is evaluated before the force-disconnect-stale-connection logic
- [ ] Password verification uses SHA-256 against the stored hash (no plaintext stored or compared)
- [ ] Per-file pytest + a simulator path covering: valid creds accepted, wrong password rejected, username≠path-id rejected, missing header handled
- [ ] No OCPP session / connection-manager entry is created for a rejected connection

## Blocked by

- None - can start immediately
