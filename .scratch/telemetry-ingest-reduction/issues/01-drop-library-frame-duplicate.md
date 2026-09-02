# Stop forwarding the python-ocpp wire-frame duplicate

Status: ready-for-agent

## What to build

Every OCPP frame currently reaches New Relic **twice** — once as this service's own
summary line, and once as the python-ocpp library's raw `receive message [2, "...",
"Action", {...}]` frame. The library's line is duplicated payload: the identical wire
frame is already persisted in full on the **OCPP message log** row in Postgres, which
is what the **Logs Console** reads and what the ~90-day retention window preserves.

Silence the library's routine per-frame logging so only this service's own lines are
forwarded. The cause is that the service raises the **root** logger to INFO at startup
and the `ocpp` library's logger inherits that level — nothing opts it back down.

The Postgres **OCPP message log** must come through unchanged: same rows per frame,
same complete payload, same **OCPP Action** in `message_type`. This ticket is only
about what leaves the process on stdout/stderr for New Relic to forward.

Measured baseline: ~9.3 GB/month of Logging ingest, of which this duplicate is roughly
half. Prod emits ~354,771 log records/day.

## Acceptance criteria

- [ ] The library's per-frame `receive message` / `send message` lines no longer reach New Relic in either environment.
- [ ] This service's own **OCPP Action** summary lines still arrive at INFO.
- [ ] **OCPP message log** rows are untouched — same rows per frame, payload still complete, Action still written to `message_type`.
- [ ] **Logs Console** still lists frames and its Action filter still returns rows.
- [ ] Library **warnings and errors are still forwarded** — only routine per-frame INFO chatter is suppressed. A protocol error must not become invisible.
- [ ] Measured in New Relic: `Log` record count per environment drops materially (expect roughly half) over a comparable window. Record before/after in the comments.

## Blocked by

None — can start immediately.
