# Charger WebSocket authentication via OCPP 1.6 Security Profile 2

> **Status: PROPOSED — NOT YET IMPLEMENTED (as of 2026-07-14).** This ADR records the intended design. No code exists yet: there is no `Charger.auth_key_hash` column, no `REQUIRE_CHARGER_AUTH` flag, and no handshake authentication on the OCPP connect path — chargers currently connect unauthenticated. Written in the present tense below to describe the target design; do not read it as shipped.

Chargers authenticate their OCPP WebSocket connection with **HTTP Basic Auth over the existing WSS transport** — OCPP 1.6 **Security Profile 2**. Each `Charger` has a per-unit secret (the **Charger Auth Key**); the server stores only a **SHA-256 hash** in `Charger.auth_key_hash`. The connection is authenticated **during the WebSocket handshake, before `websocket.accept()`**, and the Basic Auth **username MUST equal the `{charge_point_id}` in the URL path**. Enforcement is **per-charger** on `auth_key_hash` presence, with a global `REQUIRE_CHARGER_AUTH` flag to close the migration window.

## Context

Before this change the OCPP endpoint (`routers/ocpp_ws.py`) had **no authentication**. `websocket.accept()` ran before any validation, and the only check (`validate_and_connect_charger`, `crud.py`) was *"does a `Charger` row exist with this `charge_point_string_id`?"* — no secret. Consequences:

- **Identity spoofing**: knowing (or guessing) a `charge_point_id` was sufficient to *be* that charger — inject `BootNotification` / `StartTransaction` / `MeterValues` / `StopTransaction`, corrupting telemetry, billing, and settlement.
- **Targeted DoS**: a new connection with an existing ID force-disconnects the live charger (the reconnection-race handling). A spoofer who knew one ID could kick the real charger offline on a loop.
- **Volumetric DoS**: `accept()` before validation meant even an invalid ID could open sockets before rejection.

TLS already terminates at nginx (Let's Encrypt) and chargers already speak `wss://`, so the *transport* half of Profile 2 was in place; only a per-charger credential was missing.

## Decision

- **Security Profile 2 (WSS + HTTP Basic Auth)**, not Profile 3 (mTLS). Username = `charge_point_id`, password = Charger Auth Key.
- **SHA-256 hash storage**, not bcrypt/argon2. The key is a high-entropy (20-byte) machine credential, not a human password — a single fast hash is not brute-forceable and avoids per-reconnect CPU cost on a fleet of flaky Quectel modems that reconnect often. Plaintext is revealed **once** at provisioning/rotation; lost key ⇒ rotate, never retrieve.
- **Check before `accept()`**, closing with `1008` on failure — fixes the accept-before-validate flaw and never creates an OCPP session for an unauthenticated caller.
- **Auth precedes the force-disconnect-stale-connection logic**, so an unauthenticated caller can never kick a live charger offline via the reject path.
- **Per-charger enforcement** keyed on `auth_key_hash`: null ⇒ legacy (allowed, logged `charger.connection_insecure`); non-null ⇒ enforced. Global `REQUIRE_CHARGER_AUTH` flag flips to reject null-hash chargers once the insecure count reaches zero.
- **Provisioning/delivery is out of scope for the server** — charger-side change-config tooling writes the key onto the unit. The server only generates, hashes, stores, and reveals-once.

## Considered alternatives

- **Security Profile 3 (mTLS client certs).** Rejected for now: stronger, but requires a client-cert PKI (issuance, rotation, revocation) and fights the Quectel modems' single-TLS-context limitation ([[project-quectel-ws-firmware-limitation]]), for marginal gain on a network where we control both ends. Revisit if we ever need cross-operator roaming trust.
- **bcrypt/argon2 for `auth_key_hash`.** Rejected: deliberate slowness protects low-entropy human passwords; it only adds latency on every reconnect here. Wrong tool for a high-entropy machine secret.
- **Reversible/encrypted storage so ops can retrieve a key.** Rejected: a DB dump would expose every charger's live credential. Reveal-once + rotate is strictly safer and the charger-side tooling removes the need to retrieve.
- **Server-pushed provisioning via `ChangeConfiguration(AuthorizationKey)`.** Not needed — charger-side tooling owns delivery. (The OCPP standard supports it; we simply don't drive it from the server.)
- **Big-bang enforcement (set all keys, flip one switch).** Rejected: a single misconfigured charger becomes an outage, which fights the flaky-modem reality. Per-charger enforcement shrinks exposure unit-by-unit and lets provisioning proceed without a flag day.
- **Enforce auth at nginx (htpasswd / `auth_request`).** Rejected as the primary mechanism: the username==path-id invariant and per-charger secret live in the app DB, and nginx has no clean access to them. Edge **rate-limiting** remains valuable but is a separate concern (see Consequences).

## Consequences

- A new nullable `Charger.auth_key_hash` column. Provisioning and rotation share one code path (rotation is provision-from-non-null); there is no grace overlap — a charger is briefly unauthenticated between rotate and re-load, fails closed, and reconnects once the new key is loaded.
- **Migration is observable, not timed.** `charger.connection_insecure` (null-hash connect) is the burn-down signal; watch it trend to zero, *then* set `REQUIRE_CHARGER_AUTH`. During the window an un-provisioned ID is still spoofable (it has no secret yet) — unavoidable, and shrunk charger-by-charger.
- Observability reuses existing shapes: `charger.auth_provisioned` / `charger.auth_rotated` audit events; `charger.connection_rejected` with `reason=auth_failed` (attack/misconfig signal) via `record_websocket_rejected`.
- **Volumetric DoS is only partly addressed.** Auth makes each attempt cheap (one indexed lookup + a SHA-256) and harmless, but does not cap attempt *rate*. Edge rate-limiting at nginx (`limit_req`/`limit_conn` on `location /ocpp/`) is deliberately deferred to a separate ticket — it needs careful tuning because chargers sit behind **carrier-grade NAT** and share public IPs, so per-IP limits must stay generous.
- A new env var `REQUIRE_CHARGER_AUTH` must be threaded through all three compose files' `backend.environment:` blocks per the project's env-var contract, not just the `.env.example` files.
