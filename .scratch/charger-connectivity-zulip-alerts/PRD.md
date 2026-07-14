# PRD: Charger-connectivity Zulip alerts (temporary)

Status: ready-for-agent

## Problem Statement

The ops/engineering team currently monitors charger WebSocket connectivity — chargers connecting, disconnecting, and being rejected at the handshake — by watching the admin dashboard (the `/api/admin/logs/audit` connect/disconnect view). This means someone has to actively keep a browser tab open and eyeball it. There is no push signal: nobody is notified when a charger drops, reconnects, or is turned away. The team already has a Zulip workspace and wants those same connectivity events to land in Zulip so they can watch the feed passively (and on mobile) instead of babysitting the dashboard.

This is explicitly a **temporary convenience** — a stopgap that mirrors the dashboard's connect/disconnect stream into chat until a more durable monitoring story exists. It is not intended to be a permanent alerting architecture.

## Solution

When a charger connects, disconnects, or is rejected at the WebSocket handshake, the backend posts a short message to a Zulip channel. Staging and production both post to the same channel, separated by Zulip topic (`production` / `staging`). Each message names the charger, the event, and — for disconnects and rejections — the reason. The feature is gated behind an off-by-default flag so it ships dark and is enabled per environment once the Zulip bot credentials are in place, and it is isolated in a single service file so it can be retired by flipping the flag or deleting the file.

Every connect/disconnect/reject already writes a row to the generic `audit_log` table via a single helper. That helper is the one chokepoint through which all three events flow, so the alert is emitted from there — fire-and-forget, off the request/WebSocket hot path.

## User Stories

1. As an ops engineer, I want a Zulip message when a charger disconnects, so that I learn about drops without watching the admin dashboard.
2. As an ops engineer, I want a Zulip message when a charger connects, so that I can see a charger come back online after a drop.
3. As an ops engineer, I want a Zulip message when a charger is rejected at the WebSocket handshake (tombstone or validation-failed), so that I can catch chargers being actively turned away — a failure that is invisible on the current connect/disconnect dashboard view.
4. As an ops engineer, I want each message to name the charger by its charge-point id, so that I know which charger the event is about.
5. As an ops engineer, I want disconnect and rejection messages to include the reason string, so that I can tell a natural client close from a server error, a stale-connection replacement, a tombstone reject, or a validation failure.
6. As an ops engineer, I want a distinct icon per event type (connected / disconnected / rejected), so that I can scan the feed quickly.
7. As an ops engineer, I want staging and production events in one Zulip channel but separated by topic, so that I can mute staging noise while still watching production.
8. As an ops engineer, I want the environment for each message derived from the running container's environment, so that a message can never be mislabelled as the wrong environment.
9. As an on-call engineer, I want production events to be reliably surfaced even when I am away from my desk, so that I can respond to charger fleet issues from Zulip on mobile.
10. As a platform maintainer, I want the alert integration to be off by default, so that merging the code changes nothing until credentials are configured and the flag is deliberately enabled per environment.
11. As a platform maintainer, I want the Zulip credentials supplied via environment variables threaded through all three compose files, so that the container actually receives them (per the project env-var contract).
12. As a platform maintainer, I want the app to log a loud warning at startup if alerts are enabled but credentials are missing/empty, so that a misconfigured deploy fails visibly rather than silently dropping messages.
13. As a platform maintainer, I want the Zulip POST to never delay or break the audit-log write, so that a slow or down Zulip endpoint cannot degrade charger connection handling.
14. As a platform maintainer, I want the Zulip POST to have an HTTP timeout, so that a hung Zulip endpoint cannot leak or pile up background tasks.
15. As a platform maintainer, I want Zulip delivery failures logged and swallowed rather than raised, so that a chat outage is a non-event for the OCPP server.
16. As a platform maintainer, I want all alert logic contained in a single service file with one call site, so that this temporary feature can be removed cleanly when it is no longer needed.
17. As a platform maintainer, I want the alert emitted only for the three charger connectivity actions and not for any other audit-log action, so that unrelated audit events (admin actions, webhooks) never spam the Zulip channel.
18. As a developer, I want the message-building logic unit-tested per action, so that the format for connect, disconnect, and reject is verified independently of any network call.
19. As a developer, I want a test proving the flag-off and missing-credentials paths are no-ops, so that the dark-ship guarantee is enforced by tests.
20. As a developer, I want a test proving a Zulip HTTP failure or timeout does not bubble out of the service, so that the isolation guarantee is enforced by tests.
21. As a developer, I want an integration test proving the audit chokepoint fans out to the service for the three charger actions and ignores all others, so that the scoping guarantee is enforced by tests.
22. As a platform maintainer, I want the feature to add zero database schema, so that no migration is required and there is nothing to roll back on the DB side.

## Implementation Decisions

- **Source of truth is the audit-log chokepoint, not New Relic.** New Relic was evaluated and rejected as the source: it has no charger-connect event (only `OCPPWebSocketDisconnect`), the audit log lives in Postgres which NR cannot query, and NR alert conditions are aggregate/threshold rather than per-event. The requirement is *one message per event, for connect + disconnect + reject*, which is a backend-emits design.

- **New deep module: `ZulipAlertService`** (`services/zulip_alert_service.py`). Narrow public interface — a single async entry point taking the audit `action`, the charger `entity_id`, and the audit `changes` blob. It encapsulates: enabled/credentials gating, the three `action → icon + text` message mappings, `ENVIRONMENT → Zulip topic` resolution, the timed HTTP POST to Zulip, and swallow-and-log failure handling. This is the only module with real logic and the only one designed to be tested in isolation.

- **One insertion point: the audit-log write helper.** The three connectivity actions (`charger.connected`, `charger.disconnected`, `charger.connection_rejected`) all flow through the single `log_audit_event` helper. The hook lives there: after the audit row is created, if the action is one of the three, fan out to `ZulipAlertService` via the existing `safe_create_task` fire-and-forget wrapper. The hook is a thin conditional — no logic beyond the action-membership check — so the audit helper stays generic and the alert code stays in the service. The alert POST runs in its own background task, decoupled from the audit write's own background task.

- **Delivery mechanism: Zulip REST messages API.** The service POSTs to `{ZULIP_SITE}/api/v1/messages` using HTTP basic auth (bot email + API key) with form fields `type=stream`, `to=<channel>`, `topic=<env>`, `content=<markdown>`. A Generic bot (not an incoming-webhook bot) is used so the backend controls the full Markdown body.

- **Environment separation: one channel, topic per environment.** Both environments post to a single configured channel; the topic is the environment name (`production` / `staging`) resolved from the `ENVIRONMENT` variable each container already carries. This lets the team mute staging per-topic while watching production.

- **Message content: minimal, no enrichment lookup.** Each message uses only what the audit hook already has — an event icon, the charger `entity_id`, the event name, and (for disconnect/reject) the reason drawn from the audit `changes` blob. No per-event `Charger` DB lookup is performed. Indicative shapes:
  - `🔌 CHARGER-abc123 — connected`
  - `❌ CHARGER-abc123 — disconnected` + reason line
  - `⛔ CHARGER-abc123 — REJECTED` + reason line (reason includes the close code where the audit blob carries it)

- **Configuration and rollout (off by default).** Four env vars: `ZULIP_ALERTS_ENABLED` (default off/false), `ZULIP_SITE`, `ZULIP_BOT_EMAIL`, `ZULIP_BOT_API_KEY`. Per the project's env-var contract, these are added to `.env.example`, `.env.staging.example`, `.env.prod.example`, and to the `backend.environment:` block of all three compose files (`docker-compose.yml`, `docker-compose.staging.yml`, `docker-compose.prod.yml`) with sensible defaults. The `main.py` startup path logs a loud warning if `ZULIP_ALERTS_ENABLED` is true but any credential is empty. Off-by-default means the merge is inert until an operator sets credentials and flips the flag per environment.

- **Failure isolation and timeout.** The Zulip POST is issued from its own `safe_create_task` and carries an HTTP timeout. Delivery failures (non-2xx, timeout, connection error) are logged and swallowed; they never propagate to the audit write or the connection-handling path.

- **No schema change / no migration.** The feature reads existing audit data in-flight and writes nothing to the database. Aerich is not involved.

- **Volume is accepted and intentional.** "Each connect and disconnect" is roughly 80–100 messages/day/environment on production (each disconnect is typically followed by a reconnect). This mirrors the dashboard firehose the team already watches and is acceptable for a temporary tool; no dedup, flap-suppression, or rate-limiting is added.

- **Scope covers connection rejections.** In addition to connect/disconnect, `charger.connection_rejected` (tombstone and validation-failed handshakes) is alerted — a high-signal condition not visible on the current dashboard view, obtainable from the same chokepoint at near-zero extra cost.

## Testing Decisions

Good tests here assert **external behavior** of the `ZulipAlertService` — what message would be sent, and whether a send is attempted at all — without asserting private helpers or internal call sequencing. The HTTP client is the seam: tests stub/mock the outbound POST and assert on the request that would be made (or that none is), never reaching a real Zulip. This mirrors existing backend service tests that mock outbound HTTP (e.g. the Razorpay and webhook service tests) rather than hitting live endpoints.

Modules under test:

- **`ZulipAlertService` (unit).**
  - Formats the correct message for each of the three actions (`charger.connected`, `charger.disconnected`, `charger.connection_rejected`), including the reason line for disconnect/reject drawn from the `changes` blob.
  - Resolves the topic from `ENVIRONMENT` (e.g. `production` vs `staging`).
  - Flag off → no POST attempted (no-op).
  - Enabled but credentials missing/empty → no POST attempted (no-op).
  - Zulip returns a non-2xx / raises timeout / raises connection error → the service logs and returns normally; the exception does not propagate.

- **Audit chokepoint hook (integration).**
  - `log_audit_event` for each of the three charger actions fans out to the service (assert the service entry point is invoked with the right action/entity/changes).
  - `log_audit_event` for an unrelated action does **not** fan out (no service invocation), proving the scoping guarantee.

Prior art: existing per-file service tests under `backend/tests/` that mock outbound HTTP and background-task fan-out. Follow the per-file pytest execution pattern (run the affected test files directly, not a single monolithic `pytest` run).

## Out of Scope

- Any New Relic alert condition, workflow, or NR→Zulip notification destination (NR is not the source for this feature).
- A permanent/durable alerting architecture, escalation, paging, or on-call rotation integration.
- Deduplication, flap-suppression, rate-limiting, or spike/threshold aggregation — the per-event firehose is intentional for this temporary tool.
- Enriching messages with charger display name, site, connector, or active-transaction context (no per-event DB lookup).
- Alerting on any audit action other than the three charger connectivity actions.
- Frontend/admin-UI changes; the dashboard view is unchanged.
- Two-way Zulip interaction (acknowledging, commands, threads beyond the per-env topic).
- Backfill of historical audit events into Zulip.

## Further Notes

- **Operator prerequisites (Zulip side):** create a **Generic bot** and obtain its bot email + API key; note the Zulip site URL; create/choose the target channel and subscribe the bot to it. These four values populate the env vars; until they are set and the flag is flipped, the feature stays dark.
- **Retirement:** because all logic is in `services/zulip_alert_service.py` with a single call site in the audit helper, the feature retires by setting `ZULIP_ALERTS_ENABLED=false` (immediate) or deleting the service file plus the one hook line and the env entries (permanent).
- **No ADR was created:** the change is temporary, reversible, and low-stakes, and introduced no new domain vocabulary, so it did not meet the bar for an ADR or a `CONTEXT.md` glossary entry.
- **Docs to update on completion (per project convention):** `docs/v1/llm-context-document.md` and `docs/v1/comprehensive-architecture-documentation.md`.
