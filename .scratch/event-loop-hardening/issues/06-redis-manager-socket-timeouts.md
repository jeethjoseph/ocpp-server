Status: done

# Add socket_timeout + health_check_interval to redis_manager.from_url

## Context

`backend/redis_manager.py:19` constructs the Redis client as:

```python
self.redis_client = redis.from_url(redis_url, decode_responses=True)
```

No `socket_timeout`, no `socket_connect_timeout`, no `health_check_interval`. If the underlying TCP connection between the backend container and the Redis container goes half-dead (network blip, container restart that didn't propagate RST, Redis OOM-killed and restarted), an in-flight `await client.get(...)` / `await client.set(...)` will **wait indefinitely** — Linux's default TCP keepalive doesn't kick in for ~2 hours.

`redis_manager` is called from many hot paths: connection establishment (`add_connected_charger`), heartbeat handling (`update_charger_status` cache writes), QR session lookups (`get_qr_session`), wallet balance cache (`get_wallet_balance`, `set_wallet_balance`). Any of these hanging forever blocks its calling coroutine indefinitely — and if it's inside an `@atomic()` block, holds an asyncpg connection.

This is defense-in-depth. We have no concrete evidence that Redis flakiness caused the 2026-06-01 freezes, but the lack of any timeout is a known gun lying around that someone will eventually fire.

## What to build

Pass explicit timeouts and health-check kwargs to `redis.from_url(...)`:

```python
self.redis_client = redis.from_url(
    redis_url,
    decode_responses=True,
    socket_timeout=5,           # operation read/write timeout
    socket_connect_timeout=2,   # initial TCP connect timeout
    health_check_interval=30,   # periodic PING to detect dead conns
    retry_on_timeout=True,      # retry once on transient timeout
)
```

Then make sure the codebase **handles** the new timeout exception class — `redis.exceptions.TimeoutError`. Callers should treat a timeout the same as a connection failure: log warning, fall through gracefully (most call sites already have `except Exception` fallbacks).

## What to change

- `backend/redis_manager.py:19` — pass the kwargs listed above.
- Sweep callers for any spots that catch only `redis.ConnectionError` and not `redis.TimeoutError` — broaden to catch both, or catch a common base (`redis.RedisError`).
- Confirm the existing fallback-mode behavior (line 24-25, `self.redis_client = None` after connect failure) doesn't change semantics. We don't want a transient ping timeout during `health_check_interval` to permanently disable the client.

The values (5s op, 2s connect, 30s health) match the conservative defaults used in similar production systems. They're tight enough to surface real problems quickly and loose enough not to false-trip on a momentary spike.

## Acceptance criteria

- [ ] `redis.from_url(...)` call passes `socket_timeout`, `socket_connect_timeout`, `health_check_interval`, `retry_on_timeout`.
- [ ] Callers that catch `redis.ConnectionError` also catch `redis.TimeoutError`. A grep for `except redis\.` or `except.*ConnectionError` will surface them.
- [ ] Backend starts cleanly and connects to Redis (look for "Connected to Redis successfully" in logs).
- [ ] Existing tests pass via `docker exec ocpp-backend pytest`.
- [ ] Manual sanity: stop the Redis container (`docker stop ocpp-redis-staging`); verify the backend logs a TimeoutError within ~5 seconds (not 2 hours) on the next Redis call; restart Redis and verify backend reconnects automatically.

## Notes for the agent

If `retry_on_timeout=True` causes test flakiness (the test mocks an unresponsive Redis and the retry loop hangs), drop the retry and rely on caller-side fallback. The timeouts are the load-bearing change; retry is the nicety.

## Blocked by

None — can start immediately. Independent of all other issues.
