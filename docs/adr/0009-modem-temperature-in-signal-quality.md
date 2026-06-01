# Modem temperature lives in `signal_quality`, not `meter_value`

The OCPP `DataTransfer` packet with `vendorId=VoltLync, messageId=SignalQuality` carries three values per send: `rssi`, `ber`, and (as of mid-2026) `temperature`. The first two have lived in the `signal_quality` table since the charger fleet went online. The temperature column lives on the same row — not on `meter_value`, despite the natural pull of "it's a measurement, put it with the other measurements."

The `signal_quality` table name is therefore a misnomer post-2026-06-01. A future rename to `charger_telemetry` (or similar) is on the table; doing it as part of this feature would have been a refactor, not a feature, so it is deferred. New contributors should not be misled — the row is the canonical home for **all modem-emitted telemetry**, not strictly signal-quality fields.

## Considered alternatives

- **Put it on `meter_value` (as originally planned)**. Rejected. `meter_value` rows are per-transaction — they only exist while a session is active and are FK-joined to a `Transaction`. Modem temperature is sampled continuously, including when the charger is idle. The most operationally useful read of this signal is *idle thermal trend in summer* — a charger overheating on a hot afternoon with no load is a real fleet concern. Storing on `meter_value` would lose that signal entirely, plus introduce an awkward FK to a transaction that doesn't logically own the reading.

- **New `charger_telemetry` table, deprecate `signal_quality` over time**. Rejected for this change set. The "correct" long-term shape is a normalized table with `(charger_id, timestamp, measurand, value, unit)` rows for arbitrary modem fields. Migrating the existing `signal_quality` row to that shape is a refactor with rewriting every read path (the admin signal-quality endpoint, the status card, future per-metric dashboards) and a substantial backfill. The feature here is "stop dropping a value the hardware sends." Deferring the rename is the correct call; the cost of a future rename is bounded.

- **Single nullable `temperature_celsius` column on `signal_quality`**. Chosen. One Aerich migration (`43_..._add_signal_quality_temperature.py`), one parser line in `ChargePoint._handle_signal_quality`, one new field in `SignalQualityResponse`. Backward compatible — older firmware that omits `temperature` continues to land as before, with the new column NULL.

## Consequences

- The `signal_quality` table name no longer matches what it stores. A future contributor reading the schema will wonder why temperature is here. This ADR is the answer. Do not migrate it to `meter_value` without revisiting this decision.

- The handler tolerates non-numeric `temperature` values (firmware bug, schema drift) by dropping the field to NULL and accepting the rest of the packet. `rssi` and `ber` are load-bearing fields — rejecting the whole packet for a malformed optional value would discard valuable signal-quality data on every misbehaving frame.

- The admin signal-quality endpoint (`GET /api/admin/chargers/{id}/signal-quality`) now returns `temperature_celsius` on each historical row and `latest_temperature_celsius` on the envelope, matching the existing `latest_rssi` / `latest_ber` pattern. No new endpoint was added — the chart card on the admin charger detail page sources from the same endpoint as the rest of the modem telemetry surface.

- A future rename of the table requires:
  - Renaming the model class and table reference.
  - Renaming the endpoint path (or keeping a redirect alias for one release).
  - Updating this ADR with a forward pointer to the rename ADR.

  None of that is blocking the temperature feature. Track it as a separate ticket when the misnomer becomes load-bearing on day-to-day reading of the schema.

- Cable / socket / EV-side temperature (the OCPP-spec `Temperature` measurand with `location=Cable|Outlet|EV`) is **not** the same signal. If the fleet ever starts emitting `Temperature` as a MeterValues sampledValue, that is per-transaction data and belongs on `meter_value`. The two are orthogonal — modem temp answers "is the charger overheating in idle?", cable temp answers "is the cable overheating during a high-power session?". Don't conflate them by reusing one column for both.
