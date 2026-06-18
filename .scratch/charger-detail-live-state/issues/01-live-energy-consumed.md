# Live energy consumed during active session

Status: ready-for-agent

## What to build

The admin charger detail page (`/admin/chargers/{id}`) currently shows a "Energy Consumed" tile inside the **Current Charging Session** card, but it reads `Transaction.energy_consumed_kwh` which is **only populated at StopTransaction**. During an active session the tile is stuck at `0.00 kWh`.

Fix by deriving the value live on the backend and wiring the existing UI tile to it.

The derivation: `live_energy_kwh = latest_meter_value.reading_kwh − transaction.start_meter_kwh`. Return `None` if `start_meter_kwh` is `NULL` (legacy rows); the UI renders `—` in that case.

Do **not** persist this incrementally onto `Transaction.energy_consumed_kwh` — that column's contract is "finalised value at StopTransaction" and overloading it would race with the StopTransaction writer and break billing recovery code.

As part of this work, add a "Live energy consumed" entry to `CONTEXT.md` clarifying the column-vs-derived distinction so the next reader doesn't reach for the column and wonder why it's null mid-session.

## Acceptance criteria

- [ ] `GET /api/admin/transactions/{transaction_id}` response includes a `live_energy_kwh` field (Decimal as string, or `null`).
- [ ] For a transaction with a `start_meter_kwh` and at least one MeterValue, the field equals `latest_reading_kwh − start_meter_kwh`.
- [ ] For a transaction whose `start_meter_kwh` is NULL, the field is `null`.
- [ ] For a finalised transaction, the field still computes from the last MeterValue (it does not switch to reading the stored `energy_consumed_kwh`).
- [ ] The "Energy Consumed" tile inside the Current Charging Session card on `frontend/app/admin/chargers/[id]/page.tsx` renders the new field, falling back to `—` when null.
- [ ] On an active session in staging the tile updates as new MeterValues arrive (verifiable by polling cadence — already 2s when a transaction is active).
- [ ] `Transaction.energy_consumed_kwh` is NOT written by any code path added in this change.
- [ ] `CONTEXT.md` has a new glossary entry under an appropriate section explaining the live-derived vs final-stored distinction.
- [ ] Backend test covers: NULL start_meter, no MeterValues, normal active session, finalised session.
- [ ] Frontend production build (`cd frontend && npm run build`) passes.
- [ ] Backend tests (`docker exec ocpp-backend pytest`) pass, excluding the documented `gst_rate_percent` baseline flake in `CLAUDE.md`.

## Blocked by

None — can start immediately.
