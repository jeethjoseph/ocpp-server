# Slice 1 — End-to-end charger-disconnect → Zulip (the spine)

Status: ready-for-agent
Type: AFK

## Parent

PRD: `.scratch/charger-connectivity-zulip-alerts/PRD.md`

## What to build

Build the complete backend-emits-to-Zulip integration for a single connectivity event — a charger **disconnect** — cutting through every layer: the alert service, the audit-log hook, config/env plumbing, startup validation, and tests.

When a charger disconnects, the backend posts a short Markdown message to a configured Zulip channel, in a topic named after the running environment (`production` / `staging`, from the `ENVIRONMENT` variable each container already carries). The message names the charger by its charge-point id and includes the disconnect reason, e.g.:

```
❌ CHARGER-abc123 — disconnected
   reason: Natural WebSocket disconnect
```

The alert originates from the single `log_audit_event` chokepoint (through which every `charger.disconnected` audit row already flows), fanned out via the existing `safe_create_task` fire-and-forget wrapper so it never delays or breaks the audit write. All alert logic lives in one new service (`ZulipAlertService`) with a narrow async entry point taking the audit `action`, charger `entity_id`, and `changes` blob; it encapsulates gating, `ENVIRONMENT`→topic resolution, message formatting, the timed HTTP POST to Zulip (`POST {ZULIP_SITE}/api/v1/messages`, HTTP basic auth as a Generic bot, form fields `type=stream`/`to`/`topic`/`content`), and swallow-and-log failure handling.

The feature ships **dark**: four env vars — `ZULIP_ALERTS_ENABLED` (default off), `ZULIP_SITE`, `ZULIP_BOT_EMAIL`, `ZULIP_BOT_API_KEY` — are added to `.env.example`, `.env.staging.example`, `.env.prod.example`, and to the `backend.environment:` block of all three compose files. On startup, if alerts are enabled but any credential is empty, the app logs a loud warning. No database schema change; no migration.

For this slice, only `charger.disconnected` triggers a message; connect and reject are added in Slice 2.

## Acceptance criteria

- [ ] A new `ZulipAlertService` exposes a single async entry point (action, entity_id, changes) and is the only place alert logic lives.
- [ ] On a `charger.disconnected` audit event, a Markdown message with the ❌ icon, the charger `entity_id`, and the reason (from the audit `changes` blob) is POSTed to Zulip.
- [ ] The Zulip topic is resolved from `ENVIRONMENT` (`production` / `staging`); the channel and credentials come from env vars.
- [ ] The alert is emitted from the `log_audit_event` chokepoint via `safe_create_task`; the audit-log write is unaffected by Zulip latency or failure.
- [ ] `ZULIP_ALERTS_ENABLED=false` (default) → no POST attempted.
- [ ] Enabled but any credential empty → no POST attempted, and a loud warning is logged at startup.
- [ ] The Zulip POST carries an HTTP timeout; a non-2xx response, timeout, or connection error is logged and swallowed (never raised).
- [ ] Four env vars are present in `.env.example`, `.env.staging.example`, `.env.prod.example`, and in `backend.environment:` of `docker-compose.yml`, `docker-compose.staging.yml`, `docker-compose.prod.yml`, each with a sensible default.
- [ ] Unit tests (service): disconnect message format is correct; topic resolves from `ENVIRONMENT`; flag-off = no-op; missing-creds = no-op; HTTP failure/timeout does not bubble.
- [ ] Integration test (hook): `log_audit_event` for `charger.disconnected` fans out to the service.
- [ ] No new migration; `docker exec ocpp-backend pytest` on the new test file(s) passes.

## Blocked by

None - can start immediately.
