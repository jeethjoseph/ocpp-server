# Prod backend log retention is ~1.3 days — too short for incident forensics

Status: ready-for-human (largely satisfied — see update)

## What to build

During the WS-disconnect RCA (2026-07-06), OCPP-frame forensics for the incident
transactions (4 Jun / 25 Jun / 26 Jun) were **impossible** because
`docker logs ocpp-backend-prod` only reached back to 2026-07-05 02:58 — roughly
**1.3 days** on a busy day. The DB carried the durable audit trail, but raw OCPP
message logs (MeterValues / BootNotification / StopTransaction frames) needed to
reconstruct charger behavior were already rotated out.

Per `CLAUDE.md`, `docker-compose.prod.yml` caps the backend at
`20m × 5 = 100 MB`. At current write volume that is ~1.3 days. Decide a target
retention (e.g. 7–14 days for the backend specifically) and raise the cap, or
ship OCPP frames to a longer-lived sink (CloudWatch / an S3 log archive) so
incident forensics older than a day are possible.

## Acceptance criteria

- [ ] Backend log retention target agreed (proposed: ≥7 days).
- [ ] Either the `logging:` cap on the backend service in `docker-compose.prod.yml` is raised to meet it (mind the 4 GB host disk — see the on-host-build memory), OR a durable off-host log sink is wired.
- [ ] Verified on the box that `docker logs ocpp-backend-prod` (or the sink) reaches back the target window.

## Update (2026-07-06) — durable sink already exists

Application logs (incl. raw OCPP frames — MeterValues/BootNotification/DataTransfer)
are **already forwarded to New Relic** (`NEW_RELIC_APPLICATION_LOGGING_FORWARDING_ENABLED`),
entity `OCPP-Server-Production`, **~30-day** retention. This was used throughout the
WS-disconnect RCA to pull frames the 1.3-day container logs no longer had. So the
"forensics impossible" premise is **mostly resolved** — NR is the long-lived sink.

Residual, now a narrow decision (not a build):
- **30 days was *just* short for txn 870** (4 Jun, ~32 days old at investigation) — it
  missed the NR floor by ~2 days. Decision: is 30 days enough, or extend NR log
  retention (cost) to e.g. 45–60 days for incident lead time?
- The container 1.3-day tail is fine for live debugging; only worth a modest bump if
  on-box `docker logs` history matters when NR is unavailable — and only if the 4 GB
  prod disk allows (it has thrashed before; don't raise blindly).

No code change is clearly required. This is a NR-retention / cost call for a human.

## Blocked by

None.

## Comments

Weigh against host disk pressure — the prod box is 4 GB and has thrashed on disk
before. A larger local cap trades disk for retention; an off-host sink avoids
that trade but adds a moving part. Staging uses a single `x-default-logging`
anchor (5×50 MB); prod caps are deliberately per-service — don't unify blindly.
