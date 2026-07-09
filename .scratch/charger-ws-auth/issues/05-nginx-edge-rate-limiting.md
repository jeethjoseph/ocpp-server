# 05 — Follow-up: nginx edge rate-limiting on /ocpp/ (NAT-aware)

Status: ready-for-human

## What to build

The deferred volumetric-DoS layer from ADR 0020. Charger auth (slices 01–04) closes the spoofing/impersonation hole and makes each connection attempt cheap, but it does not cap the *rate* of attempts. Add connection rate-limiting at the nginx edge on `location /ocpp/`.

This is **HITL**: the limits must be tuned by a human against real traffic, because the fleet's chargers sit behind **carrier-grade NAT** and many legitimate chargers share a single public IP. Per-IP limits that are too tight would throttle real chargers; they must stay deliberately generous and protect only against pathological floods.

Independent of slices 01–04 — can proceed in parallel or after.

## Acceptance criteria

- [ ] `limit_req` / `limit_conn` (or equivalent) applied to `location /ocpp/` in the nginx config for staging and prod
- [ ] Limits are documented with the rationale for the chosen thresholds relative to observed per-IP charger density behind carrier NAT
- [ ] A load/soak check confirms legitimate reconnect bursts (e.g. post-outage fleet reconnect) are not throttled
- [ ] Rejected floods are visible in nginx logs/metrics for monitoring

## Blocked by

- None - can start immediately (independent of the auth slices)
