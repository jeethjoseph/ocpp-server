# CSMS pushes and maintains SessionLimit

Status: done

## What to build

Push the **Budget cap** to the charger so it can be enforced locally, which is what makes [[offline-charging-continuity]] safe: a charger that keeps delivering while unreachable and has no local energy limit delivers unbounded free energy.

Send it as a vendor `DataTransfer` with `messageId=SessionLimit`, carrying an **absolute Wh value**, immediately after the CSMS has assigned a transaction id. OCPP 1.6 has no native per-transaction energy limit — smart charging constrains power over a schedule, not cumulative energy — so a vendor extension is the idiomatic answer here.

Four rules that are load-bearing:

- **Keyed on `transactionId`, never `idTag`.** The id tag is a per-`User` value reused across every session that customer ever has, so it cannot identify a session — and the ambiguity is worse against a limit the charger persists across reboots.
- **Round the Wh conversion down.** Rounding up makes over-delivery past what the customer paid structural rather than bounded by RemoteStop latency.
- **Absolute value, idempotent, re-sendable.** Re-assert the current limit on every reconnect, and re-push whenever the budget changes.
- **The charger is the source of truth; the server-side budget check stays as a redundant failsafe.** Whichever enforcer fires first wins — the existing flag-less at-least-once pattern, extended across the link.

**Re-assert on the WebSocket connect path, not only on `BootNotification`.** Under continuity firmware the common reconnect is a plain WebSocket re-establish with no reboot, so a limit re-asserted from the Boot handler would miss most reconnects. Hook the connect event in `connection_manager`: on connect, look up open transactions for the charger and push each one's current limit. Boot then needs no separate hook.

**Handle the `StopDetail` DataTransfer.** OCPP 1.6 has no budget-stop reason code, so a charger that opens the contactor on its local limit sends `StopTransaction` with `reason: "Local"` and follows it with a vendor `DataTransfer` `messageId=StopDetail` carrying `{"transactionId": ..., "reason": "SessionLimit"}`. `on_data_transfer` routes only `SignalQuality` and `GetLastMeterValue` today. Add the route, record the detail reason on the transaction (a reported-only field, alongside the OCPP `stop_reason`), and count it — without it a budget-cap stop is indistinguishable from the customer pressing stop, and that count is what says how often the charger-side cap is doing its job.

Shape the payload fields as `maxEnergy` / `maxCost` / `maxTime` even though only the first is populated, mirroring the native construct that lands in OCPP 2.1, so a later migration is a transport swap rather than a redesign.

Verifiable end-to-end against the charger simulator without firmware existing. Per project convention, ship the simulator support and the firmware-facing message spec alongside the backend change.

See ADR 0031 decision 2 and the **Budget cap** entry in CONTEXT.md.

## Acceptance criteria

- [x] `SessionLimit` is sent once the transaction id exists, carrying an absolute Wh value keyed on `transactionId`
- [x] The Wh conversion rounds down; a test pins the direction
- [x] The current limit is re-asserted on WebSocket connect for every open transaction on the charger, whether or not a `BootNotification` follows
- [x] A `StopDetail` DataTransfer is routed, its reason recorded on the transaction without overwriting the OCPP `stop_reason`, and counted; an unknown `transactionId` is logged and answered `Rejected`, never raised
- [x] A budget change re-pushes the new absolute value; sending the same value twice is harmless
- [x] Internal-role sessions receive no limit (no budget cap applies, per ADR 0004)
- [x] The charger's response — accepted, rejected, unanswered — is logged and counted, and a rejection does not fail the session
- [x] The server-side budget check still fires independently
- [x] Simulator handles the message; firmware-facing spec written

## Blocked by

None - can start immediately

## Shipped 2026-09-15

**SHIPPED 2026-09-15 (migration 65).** `services/session_limit_service.py`: `compute_session_limit_wh` reads the SAME Redis rows the server-side checks read (`qr_session:` first, then `wallet_session:`, each with its DB rebuild) and inverts the cost formula — `budget / (rate × (1 + gst))`, rounded DOWN to whole Wh; `push_session_limit(cp_id, txn_id, trigger)` sends `DataTransfer vendorId=VOLTLYNC messageId=SessionLimit data={transactionId, maxEnergy, maxCost:null, maxTime:null}` and classifies the reply (accepted / rejected / unknown_message_id / unknown_vendor_id / no_response / timeout / not_connected / error) into `Custom/OCPP/SessionLimit/{outcome}` + NR event `OCPPSessionLimitPushed`; nothing fails the session. `maxEnergy` is TOTAL session energy from `meterStart` — the whole current limit, never an increment. Triggers: `ChargePoint.after_start_transaction` (`@after('StartTransaction')`, reading a txn id the handler stashed so a rejected start never pushes a stale id); `ChargePoint.reassert_session_limits` scheduled from `routers/ocpp_ws.py` on EVERY WebSocket connect for all `OPEN_TRANSACTION_STATES` (Boot needs no hook); and on budget change — **ADR 0021 stacking must call `push_session_limit(..., trigger="budget_change")`**, there is no other live trigger. Internal-role sessions have no session row → no push. `StopDetail` inbound (`_handle_stop_detail`) records `Transaction.stop_detail_reason` beside `stop_reason`, counts `Custom/OCPP/StopDetail/{reason}`, answers Rejected for unknown/malformed without raising. Spec: `docs/firmware/session-limit-spec.md` (incl. the rule that a transaction with no accepted limit opens the contactor on link loss). Simulator: `ocpp_simulator_production.py` accepts SessionLimit and self-stops with Local + StopDetail. 20 tests in `test_session_limit.py`; 200 green across touched suites.

Note for ADR 0021: stacking is not implemented yet (all four issues in `.scratch/stackable-qr-payments/` are open); the budget-change trigger therefore exists only as the `push_session_limit` hook, exercised by test, and the stacking issue 01 now carries the requirement to call it.
