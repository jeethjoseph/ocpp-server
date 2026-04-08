# Voltlync OCPP Runbooks

Operational triage guides for the OCPP server backend. Each runbook is the
**single source of truth** for responding to a specific alert. They are
referenced from New Relic alert conditions via the `runbook_url` field so the
on-call engineer gets a direct link in the page payload.

## Format

Every runbook follows the same H2 structure so engineers learn one shape:

| Section | Purpose |
|---|---|
| **Symptom** | What fired the page (log line / metric / Sentry event) |
| **What it means** | One-paragraph plain-English explanation |
| **When it's normal** | Table of scenarios where this is benign |
| **Triage** | Decision tree with copy-pasteable commands |
| **Mitigation** | Immediate actions to stop bleeding |
| **What NOT to do** | Prevents panic-driven mistakes |
| **Customer impact** | How to identify affected customers |
| **Escalation** | Who to call and when |
| **Related** | Code paths, metrics, related runbooks |

## Active runbooks

| File | Triggers on | New Relic alert |
|---|---|---|
| [stale-suspended-transactions.md](./stale-suspended-transactions.md) | `OCPPStaleSuspendedSwept` event with `count > 0` at startup | OCPP / Stale Suspended Sweep |
| [disconnect-stop-spike.md](./disconnect-stop-spike.md) | `count(*) FROM OCPPDisconnectStopped > 5` in 10 minutes | OCPP / Disconnect Stop Spike |
| [zero-energy-stop-spike.md](./zero-energy-stop-spike.md) | `count(*) FROM OCPPZeroEnergyStopped > 3` in 10 minutes | OCPP / Zero Energy Stop Spike |

## New Relic alert configuration

Each runbook above must be linked from a New Relic alert condition. One-time
admin task — configure via the New Relic UI or Terraform:

```
For each runbook:
  Name:        <see table above>
  Type:        NRQL static alert
  Query:       <NRQL from the runbook's "Symptom" section>
  Threshold:   <see runbook's severity table>
  Priority:    Warning (or Critical for P1)
  Runbook URL: https://github.com/<org>/ocpp-server/blob/main/docs/runbooks/<file>
```

The `runbook_url` field is the magic — New Relic embeds it in every Slack /
PagerDuty / email notification, giving the on-call engineer a one-click path
from the alert to the triage.

## Code paths referenced by runbooks

- Disconnect handling: `backend/services/disconnect_handler.py`
- Transaction finalization: `backend/services/transaction_finalizer.py`
- Zero-energy watchdog: `backend/services/zero_energy_watchdog.py`
- Wallet billing: `backend/services/wallet_service.py`
- Metrics: `backend/services/monitoring_service.py` (`OCPPMetrics` class)
