# Align billing-retry stale-suspended sweep with the disconnect window

Status: done

## What to build

The billing-retry background loop's stale-suspended cleanup
(`BillingRetryService._cleanup_stale_suspended_transactions`) force-stops any
`SUSPENDED` transaction older than `SUSPEND_TIMEOUT_SECONDS` (5 min). But a
transaction suspended by a raw WebSocket **disconnect** is meant to get a
30-minute reconnect grace window (`DISCONNECT_SUSPEND_TIMEOUT_SECONDS=1800`).
Because the billing-retry loop runs every 30 min and uses the 5-min cutoff for
*all* suspended rows regardless of how they were suspended, it pre-empts the
disconnect timer and kills live sessions inside their legitimate window.

Change the sweep's cutoff to the longest legitimate suspend window plus a
buffer — `max(DISCONNECT_SUSPEND_TIMEOUT, SUSPEND_TIMEOUT) + 60` — reusing the
existing env vars. This mirrors the already-correct startup sweep in
`disconnect_handler.sweep_stale_suspended_transactions`. The billing-retry
sweep then behaves as a true backstop (catches sessions orphaned by a process
restart) instead of a pre-emptor.

A single SUSPENDED row does not record *why* it was suspended (disconnect vs
reboot), so the sweep must assume the worst-case (longest) window — this is
intentional and matches the startup sweep.

### Confirmed incident (prod, 2026-06-18)

QR session txn 949 on charger `b226ca5e…`:
- 06:08:51Z — WS disconnect → suspended (30-min timer scheduled to fire 06:38:51Z)
- 06:17:36Z — billing-retry sweep force-stopped it at **8m45s**, refunded ₹16.94
- 06:27:27Z — charger rebooted and reconnected at **18.5 min** — inside the
  intended 30-min window, but the session was already gone.

## Acceptance criteria

- [ ] `_cleanup_stale_suspended_transactions` uses a cutoff of
      `max(DISCONNECT_SUSPEND_TIMEOUT, SUSPEND_TIMEOUT) + 60` seconds, derived
      from the existing env vars (no new env var introduced).
- [ ] A transaction suspended via disconnect less than
      `DISCONNECT_SUSPEND_TIMEOUT_SECONDS` ago is NOT swept by the billing-retry
      loop.
- [ ] A transaction suspended longer than the max window IS still swept
      (backstop behavior preserved).
- [ ] The atomic compare-and-swap guard against racing `_suspend_timeout` is
      retained.
- [ ] Regression test covering the incident shape: a disconnect-suspended txn
      at ~9 min survives the sweep; the same txn past the full window is swept.
- [ ] `docker exec ocpp-backend pytest` passes for the affected test files.

## Blocked by

None - can start immediately

## Comments

**Implemented 2026-06-18.** `BillingRetryService._cleanup_stale_suspended_transactions`
cutoff changed from `SUSPEND_TIMEOUT_SECONDS` (5 min) to
`max(DISCONNECT_SUSPEND_TIMEOUT, SUSPEND_TIMEOUT) + 60`, matching the startup
sweep. Regression test added at `tests/test_billing_retry_stale_suspended.py`
covering the incident shape (txn suspended 9 min ago with a 30-min disconnect
window survives) and the backstop (txn past max window + buffer is swept).
Superseded internally by issue 02, which routes this through the shared helper.
Verified: `pytest tests/test_billing_retry_stale_suspended.py tests/test_disconnect_handler.py` — all green.
