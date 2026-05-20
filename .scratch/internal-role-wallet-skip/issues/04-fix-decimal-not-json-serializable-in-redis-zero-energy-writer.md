# Fix `Decimal is not JSON serializable` in redis_manager zero-energy state writer

Status: ready-for-agent

## What to build

The Redis writer in `redis_manager` that caches zero-energy state for the watchdog passes a `Decimal` directly to `json.dumps` without a coercion or a `default=` handler. Every active charging session produces a fresh error every ~10 seconds:

```
ERROR redis_manager: Failed to set zero-energy state for transaction <N>:
  Object of type Decimal is not JSON serializable
```

On staging today: **223 occurrences in the recent log window**, firing on every MeterValues frame of every active session. The zero-energy watchdog state never gets written, so the watchdog can't detect stalled sessions for any transaction that hits this path. Pre-existing bug, unrelated to the internal-role work but bundled in the same PR per the 2026-05-19 grilling.

### Plan

- Find the `json.dumps` call (or whatever serializer the writer uses) in `backend/redis_manager.py` for the `zero_energy:{txn_id}` key.
- Pass `default=str` so any `Decimal` in the payload serializes as its string representation (preserves precision — `float(decimal)` would silently lose digits and would be wrong for currency or kWh values elsewhere if the writer is reused).
- Verify there's no analogous bug in the QR-session or wallet-session writers in the same module — if there is, fix them with the same handler. Pre-existing memory note: similar serialization gotchas have bitten before.
- Add a regression test: construct a payload containing a `Decimal`, serialize it through the writer, assert the call succeeds and round-trips losslessly.

### Out of scope

- Refactoring `redis_manager` to use a different serializer (orjson, msgpack, etc.) — separate concern.
- Changing the watchdog state schema — same.

## Acceptance criteria

- [ ] `Failed to set zero-energy state` errors no longer appear in staging logs after deploy. (Verify by sampling 5 minutes of active-session logs post-deploy.)
- [ ] Regression test: a payload containing `Decimal("1.23")` serializes through the affected Redis writer without raising.
- [ ] Same fix applied to any sibling writer in `redis_manager` that has the same `json.dumps`-without-default pattern (search the module; bundle in one PR).
- [ ] The zero-energy watchdog (`services/zero_energy_watchdog.py`) successfully reads back state written under the fix — no decoding errors.
- [ ] No regression in the existing watchdog tests.

## Blocked by

None — independent of issues 01-03. Ships in the same PR per the grilling agreement (2026-05-19); the issue tracking stays separate for clarity.
