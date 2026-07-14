# Slice 2 — Add charger connect + rejection events

Status: ready-for-agent
Type: AFK

## Parent

PRD: `.scratch/charger-connectivity-zulip-alerts/PRD.md`

## What to build

Extend the connectivity-alert spine from Slice 1 to cover the other two events, so all three charger connectivity actions post to Zulip: connect, disconnect (already done), and handshake rejection.

- `charger.connected` → `🔌 CHARGER-abc123 — connected`
- `charger.connection_rejected` → `⛔ CHARGER-abc123 — REJECTED` with the reason from the audit `changes` blob (which includes the WebSocket close code for rejections, e.g. tombstone or validation-failed).

The `log_audit_event` hook's action set broadens from just `charger.disconnected` to all three connectivity actions, and continues to ignore every other audit action. The message-formatting in `ZulipAlertService` gains the two new action mappings; gating, topic resolution, POST, and failure handling are unchanged from Slice 1.

On completion, update the project docs (`docs/v1/llm-context-document.md` and `docs/v1/comprehensive-architecture-documentation.md`) to describe the temporary charger-connectivity Zulip alert path.

## Acceptance criteria

- [ ] `charger.connected` produces a 🔌 connected message; `charger.connection_rejected` produces a ⛔ REJECTED message including the reason/close code from the audit `changes` blob.
- [ ] The `log_audit_event` hook fans out for all three actions (`charger.connected`, `charger.disconnected`, `charger.connection_rejected`) and for no other audit action.
- [ ] Unit tests cover message formatting for the two new actions (connect, reject).
- [ ] Integration test asserts the hook fires for the three charger actions and does NOT fire for an unrelated audit action.
- [ ] `docs/v1/llm-context-document.md` and `docs/v1/comprehensive-architecture-documentation.md` describe the feature.
- [ ] `docker exec ocpp-backend pytest` on the affected test file(s) passes.

## Blocked by

- Slice 1 — `01-disconnect-zulip-spine.md`
