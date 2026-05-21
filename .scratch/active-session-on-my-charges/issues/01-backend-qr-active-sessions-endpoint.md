# Backend `qr-active-sessions` endpoint

Status: ready-for-agent

## Parent

`.scratch/active-session-on-my-charges/PRD.md`

## What to build

Public no-auth endpoint that returns the list of in-progress QR sessions for a given UPI VPA, with each session classified into one of four customer-facing sub-states.

- Route: `GET /api/public/qr-active-sessions?vpa=<upi-id>`
- Auth: none — VPA is the implicit identifier, same trust model as `/api/public/qr-transactions`.
- Rate limit: 20 req/60s/IP via the same `RedisConnectionManager.rate_limit_check` keying convention used by the history endpoint.
- VPA format validation: same `VPA_PATTERN` as the history endpoint; 400 on malformed.

For each `QRPayment` with a matching `customer_vpa` that is "active" (see sub-state rules below), the endpoint returns:

```
{
  "data": [
    {
      "qr_payment_id": int,
      "transaction_id": int | null,
      "amount_paid": string,           // Decimal stringified
      "started_at": string,            // QRPayment.created_at, ISO 8601
      "charger_name": string,
      "station_name": string,
      "franchisee_name": string | null,
      "sub_state": "waiting" | "charging" | "paused" | "stopping",
      // Null for waiting state; set for charging/paused/stopping:
      "energy_kwh": string | null,
      "spent_so_far": string | null,
      "refund_if_stopped_now": string | null,
      "power_kw": number | null,
      "budget_remaining": string | null
    }
  ],
  "total": int
}
```

Sub-state classification:

| Sub-state | `QRPayment.status` | `Transaction.transaction_status` | Other gate |
|---|---|---|---|
| `waiting` | `PAID` | no transaction OR `PENDING_START` | `now - QRPayment.created_at < STALE_PAYMENT_THRESHOLD_SECONDS` |
| `charging` | `CHARGING` | `STARTED` or `RUNNING` | — |
| `paused` | `CHARGING` | `SUSPENDED` | — |
| `stopping` | `CHARGING` | `PENDING_STOP` | — |

Anything else is not "active" and is excluded.

Live KPI computation (charging / paused / stopping only):

- `energy_kwh = latest MeterValue.reading_kwh - Transaction.start_meter_kwh` (clamped ≥ 0)
- `spent_so_far = energy_kwh × tariff_rate × (1 + gst_percent/100) + synthetic_platform_fee`
- `refund_if_stopped_now = max(0, amount_paid - spent_so_far)`
- `power_kw = latest MeterValue.power_kw` (null if no meter values yet)
- `budget_remaining = max(0, (budget_limit_paise / 100) - spent_so_far + synthetic_platform_fee)` — `budget_limit_paise` is already `amount_paid - synthetic_platform_fee`, so `budget_remaining` simplifies to `max(0, amount_paid - spent_so_far)` (same as `refund_if_stopped_now` numerically; we expose both for UI clarity)

Reuses the existing `qr_session:{txn_id}` Redis cache (`redis_manager.get_qr_session`) for `tariff_rate`, `gst_percent`, `platform_fee` (synthetic), `budget_limit_paise`, `start_meter_kwh`. Cache-miss falls back to recomputing from `Tariff` + `QRPayment` (mirror of `check_budget_and_auto_stop`'s rebuild path).

## Acceptance criteria

- [ ] Endpoint registered at `GET /api/public/qr-active-sessions` and returns 200 for a valid VPA with the documented response shape.
- [ ] Each of the four sub-states is classified correctly per the table above; non-active QRPayments (`COMPLETED`, `REFUNDED`, `FAILED`, `EXPIRED`, stale `PAID`) are excluded.
- [ ] `waiting` state returns null KPIs (no MeterValue exists yet). `charging` / `paused` / `stopping` return computed KPIs.
- [ ] Multi-session: a VPA with two concurrent active sessions returns both as separate list entries.
- [ ] Rate limit: 21st request in a 60s window returns 429, matching the history endpoint behavior.
- [ ] Malformed VPA returns 400 with the same error envelope as the history endpoint.
- [ ] Pytest covers: each sub-state, multi-session, stale-`PAID` exclusion, cache-miss fallback, rate limit.

## Blocked by

None — can start immediately.
