Status: done

# Fix Decimal-not-JSON-serializable in record_transaction_completed NR metric

## Context

Sentry issue **OCPP-BACKEND-C** ("TypeError: Decimal('0') is not JSON serializable") fires recurrently across both staging and production. The stack trace ends inside New Relic's harvest thread:

```
newrelic/core/application.py:harvest
  newrelic/core/data_collector.py:send_metric_data
  newrelic/core/agent_protocol.py:_to_http
  newrelic/common/encoding_utils.py:json_encode
  json/encoder.py:default → TypeError
```

NR's harvester runs every 60s, batches queued metrics and events, and JSON-encodes the payload before POSTing to NR's ingest. NR's encoder doesn't know how to serialize `Decimal`, so the entire harvest **fails** every time the queue contains a Decimal.

Root cause is in our code, at `backend/main.py:931`:

```python
await OCPPMetrics.record_transaction_completed(transaction_id, transaction.energy_consumed_kwh, duration_minutes)
```

`transaction.energy_consumed_kwh` is a `Decimal` (`models.py:372`: `DecimalField(max_digits=12, decimal_places=3, null=True)`). The value flows through `OCPPMetrics.record_transaction_completed` (`services/monitoring_service.py:463`):

```python
async def record_transaction_completed(transaction_id: int, energy_kwh: float, duration_minutes: float):
    MetricsCollector.increment_counter("Custom/OCPP/Transactions/Completed")
    MetricsCollector.record_metric("Custom/OCPP/Energy/Consumed", energy_kwh)     # ← Decimal enters NR
    MetricsCollector.record_event("OCPPTransactionCompleted", {
        "transaction_id": transaction_id,
        "energy_kwh": energy_kwh,                                                  # ← Decimal enters NR event
        "duration_minutes": duration_minutes,
    })
```

The signature annotates `energy_kwh: float` but Python doesn't enforce that — a Decimal sails right through. NR enqueues it; harvest fails on JSON encode.

Impact: every harvest tick where a transaction has completed in the last 60s fails to send. NR loses **all** metrics from that batch, not just the offending one. The Sentry event also captures this as an ERROR-level log event, polluting the issues list.

## What to build

Cast `transaction.energy_consumed_kwh` to `float` at the call site in `main.py`, before it enters the monitoring layer. Mirror the existing pattern at `transaction_finalizer.py:138` which already does:

```python
energy_kwh=float(transaction.energy_consumed_kwh or 0),
```

Inside `record_disconnect_stopped`. Same fix, different call site.

## What to change

`backend/main.py:931` — change the third positional arg:

```python
await OCPPMetrics.record_transaction_completed(
    transaction_id,
    float(transaction.energy_consumed_kwh or 0),
    duration_minutes,
)
```

While in the file, sweep for any other `OCPPMetrics.*` or `MetricsCollector.*` call that passes `transaction.energy_consumed_kwh` (or any other DecimalField value) without casting. Likely candidates: `OCPPMetrics.record_billing_amount(...)`, anything passing wallet amounts.

Search command for the audit:
```
grep -rn "MetricsCollector\.\|OCPPMetrics\." backend/ | grep -v "_test\|monitoring_service.py" | grep -E "amount|kwh|fee|billing"
```

## Acceptance criteria

- [ ] `main.py:931` casts `energy_consumed_kwh` to `float`.
- [ ] Any other found call sites passing a Decimal to NR are also cast.
- [ ] Add or update a test that records a completed transaction with a Decimal energy and asserts NR receives a float. (May need mocking `newrelic.agent` to spy on the call.)
- [ ] Sentry issue `OCPP-BACKEND-C` stops accumulating new events post-deploy.
- [ ] NR dashboard `Custom/OCPP/Energy/Consumed` metric and `OCPPTransactionCompleted` event start receiving data again (currently the harvest dies on every batch with a transaction).

## Blocked by

None — can start immediately. Independent of all other issues. One-line fix at `main.py:931`, plus a sweep for siblings.
