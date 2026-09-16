# Simulator for the continuity firmware, with an end-to-end late-stop check

Status: ready-for-agent

## What to build

A new simulator, `backend/simulators/ocpp_simulator_offline_continuity.py`, that behaves the way ADR 0031 asks the firmware to behave — so the CSMS side of [[offline-charging-continuity]] can be exercised end to end before any charger runs it, and so the wire behaviour the firmware team is being asked for exists as runnable code rather than prose.

Follow the conventions of `ocpp_simulator_disconnect.py` (synchronous `websocket-client`, CLI flags per scenario, hard TCP kill for a power/link loss) and of `deploy_recovery_test.py` (verify by querying postgres through `docker exec`, print a verdict, non-zero exit on failure).

**Charger behaviour modelled:**

- **Holds the contactor on WebSocket loss.** The meter keeps advancing while offline.
- **Queues transaction-related frames** (`MeterValues` with `transactionId`, `StopTransaction`) with their real timestamps and replays them in chronological order on reconnect. Heartbeats and `StatusNotification` are dropped while offline, per OCPP 1.6.
- **Reconnects with or without a `BootNotification`** (flag). Under continuity the common case is a plain re-establish. Answers `PostBootState` with `Accepted` and ignores the pushed meter value — the charger is authoritative.
- **Enforces `SessionLimit` locally.** The server now sends it (issue 04 shipped 2026-09-15; spec in `docs/firmware/session-limit-spec.md`; `ocpp_simulator_production.py` has a reference `handle_data_transfer` / `enforce_session_limit` to lift). On reaching the limit: `StopTransaction reason=Local`, then `DataTransfer messageId=StopDetail` with `reason=SessionLimit`.
- Self-starts with a seeded RFID tag (`test_rfid_830e5d98` on `MG_ROAD_STATION_01`) by default; `--wait-remote-start` to drive from the admin panel instead.

**Scenarios:**

| Flag | Flow | Proves |
|---|---|---|
| `--test-replay-in-window` | charge, hard-disconnect, meter offline for N s, reconnect, replay, charge on, stop | Replay auto-resumes `SUSPENDED`; true energy billed. Works against today's code. |
| `--test-replay-after-write-off` | charge, hard-disconnect, meter offline, **force the write-off**, reconnect, replay, late stop | Issue 01 end to end: billed fields frozen at the pre-disconnect reading, `reported_*` carry the true energy, `transaction.late_stop_recorded` audit row present, no second billing. |
| `--test-local-limit` | charge until the charger's own limit fires | Local cap fires, `StopTransaction Local` + `StopDetail SessionLimit`, `stop_detail_reason` recorded, refund equals budget minus delivered. |

**Forcing the write-off.** The real windows are 45 min / 12 h and the sweep runs every 30 min, so waiting is not practical. Add `backend/simulators/force_write_off.py`, run via `docker exec ocpp-backend`, that backdates `suspended_at` past the transaction's window and then calls the real `finalize_stale_suspended_transactions` sweep — the production write-off path, not a shortcut. Once issue 02 lands the silence clock is derived from `MeterValue.created_at` too, so the helper must backdate those as well (or the shared silence helper must expose a test seam); note this dependency when building.

The forced write-off is local-only by construction. Keep `--server` for staging, where only the in-window scenario is meaningful.

Add both files to the simulator list in `docs/v1/llm-context-document.md`.

## Acceptance criteria

- [ ] `--test-replay-in-window` passes against the local stack: transaction resumes on replay, `energy_consumed_kwh` equals the true delivered energy
- [ ] `--test-replay-after-write-off` passes: billed fields and status unchanged from the write-off, `reported_end_meter_kwh` / `reported_energy_kwh` equal the true figures, one `transaction.late_stop_recorded` audit row, no second wallet debit or QR refund
- [ ] Replayed frames carry their original timestamps and land on `MeterValue.measured_at` hours behind `created_at`
- [ ] Reconnect without `BootNotification` is supported and exercised by at least one scenario
- [ ] `SessionLimit` handling present; `--test-local-limit` asserts `stop_detail_reason == 'SessionLimit'`
- [ ] `force_write_off.py` uses the real sweep, not a status update
- [ ] Non-zero exit on any failed assertion; simulator list in the llm-context doc updated

## Blocked by

None - can start immediately (the write-off helper gains a dependency on issue 02's silence helper once that lands)
