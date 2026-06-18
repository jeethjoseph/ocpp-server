Status: ready-for-human

# New Relic dashboard + server_error alert + notification destination

## Context

Once Issue 01 ships and `OCPPWebSocketDisconnect` events are flowing into New Relic, we need a pinned dashboard so the team can baseline disconnect frequency and a single alert on the one disconnect category that should never happen (`server_error`).

This issue is HITL (`ready-for-human`) because:

1. NR alert notifications are not currently wired in this account. A notification destination must be created — Slack, email, or PagerDuty — and that decision needs the user's call on which channel and which recipients.
2. NR dashboard layout (which charts on which row, sizes, time-window defaults) is a UI-judgment task best done by a human in the NR web UI.
3. The alert policy itself, while small, must be authored against the live NR account.

The NRQL queries below are pre-defined from the grill-with-docs session — the human running this issue does not have to write NRQL, only paste it into NR.

## What to build

### Day-1 dashboard (NR dashboard, 8 charts)

| # | Chart title | NRQL |
|---|---|---|
| 1 | Disconnect mix over time | `SELECT count(*) FROM OCPPWebSocketDisconnect SINCE 7 days ago FACET disconnect_category TIMESERIES` |
| 2 | Session lifetime by category | `SELECT histogram(duration_seconds, 60, 20) FROM OCPPWebSocketDisconnect SINCE 7 days ago FACET disconnect_category` |
| 3 | Worst-offender chargers | `SELECT count(*) FROM OCPPWebSocketDisconnect SINCE 7 days ago FACET charger_id LIMIT 30` |
| 4 | Silence-before-death (heartbeat_timeout only) | `SELECT histogram(heartbeat_seconds_since_last, 30, 30) FROM OCPPWebSocketDisconnect WHERE disconnect_category = 'heartbeat_timeout' SINCE 7 days ago` |
| 5 | Mid-charge disconnect % | `SELECT percentage(count(*), WHERE had_active_transaction = true) FROM OCPPWebSocketDisconnect SINCE 7 days ago FACET disconnect_category` |
| 6 | WS close code distribution | `SELECT count(*) FROM OCPPWebSocketDisconnect SINCE 7 days ago FACET ws_close_code` |
| 7 | Reconnect storms (short sessions per charger per hour) | `SELECT count(*) FROM OCPPWebSocketDisconnect WHERE duration_seconds < 60 FACET charger_id, hourOf(timestamp) SINCE 7 days ago LIMIT 30` |
| 8 | Sessions that never booted | `SELECT percentage(count(*), WHERE messages_received = 0) FROM OCPPWebSocketDisconnect SINCE 7 days ago` |

Plus, if Issue 02 has shipped:

| 9 | Reject mix | `SELECT count(*) FROM OCPPWebSocketRejected SINCE 7 days ago FACET reject_reason TIMESERIES` |

### Alert policy

Single alert, critical severity:

```
SELECT count(*) FROM OCPPWebSocketDisconnect
WHERE disconnect_category = 'server_error'
```

- Threshold: ≥ 1 over 5 minutes
- Window function: count
- Violation closes: automatically after 1 hour of no further violations

Reasoning: `server_error` fires only when `cp.start()` raises a generic Exception (`ocpp_ws.py:124`). Expected rate is 0; any occurrence is a backend bug, not a network condition. Every other category needs baseline data before thresholds can be set.

### Notification destination

The human running this issue needs to:

1. Pick the destination channel (Slack channel? Email distribution list? PagerDuty service?). Recommended: Slack channel where existing ops alerts go, if any. Worth confirming with the team what the current paging norm is — the codebase has Sentry breadcrumbs but it's unclear whether Sentry itself is routed anywhere actionable.
2. Create the destination in NR (Alerts → Destinations).
3. Wire the alert policy from above to that destination.

## Acceptance criteria

- [ ] NR dashboard exists with all 8 queries above (9 if Issue 02 is also shipped) pinned as separate charts. Time-range default: last 7 days.
- [ ] Dashboard is shared with the team (NR has dashboard-sharing permissions per-account).
- [ ] Alert policy `OCPP server_error disconnect` exists with the threshold above.
- [ ] Notification destination exists and is wired to the alert policy.
- [ ] Test the alert: temporarily emit a synthetic `OCPPWebSocketDisconnect` event with `disconnect_category='server_error'` from a dev shell via `newrelic.agent.record_custom_event(...)` and confirm the notification fires. Then resolve.
- [ ] The destination + alert policy URLs are pasted into the comment thread of this issue for future reference.

## Out of scope

- Alerts on other disconnect categories — defer until 7–14 days of baseline data exist (separate follow-up issue at that point).
- A second alert policy for `OCPPWebSocketRejected` — same reason; baseline first.
- Long-term retention upgrade to NR Data Plus — only if the 8-day default proves insufficient after the baseline period.

## Blocked by

Issue 01 (`OCPPWebSocketDisconnect` event end-to-end) — must be deployed to staging or prod and producing events before the dashboard can render and the alert can be tested.

Issue 02 is a soft blocker only for chart #9; the rest of the dashboard works without it.
