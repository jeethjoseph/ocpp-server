Status: ready-for-agent

# Fix ConnectionManager.force_disconnect lock concurrency bug

## Context

`backend/core/connection_manager.py:97-191` defines `ConnectionManager.force_disconnect(charge_point_id, reason, ...)`. The function uses a per-charger asyncio lock to serialize cleanup for the same charger:

```python
if charge_point_id not in self._cleanup_locks:                      # line 110
    self._cleanup_locks[charge_point_id] = asyncio.Lock()           # line 111

async with self._cleanup_locks[charge_point_id]:                    # line 113
    # ... cancel heartbeat task ...
    # ... await websocket.close() ...
    # ... delete from connected_charge_points ...
    # ... await redis_manager.remove_connected_charger() ...
    # ... add tombstone ...

    # Step 6: Clean up the lock for this connection to prevent memory leak
    self._cleanup_locks.pop(charge_point_id, None)                  # line 157  ← bug

    # ... still inside the async with, then several awaits for NR metrics ...
    await OCPPMetrics.record_active_connections(...)                # line 173
    await OCPPMetrics.record_websocket_disconnect(...)              # line 180
```

The bug: `self._cleanup_locks.pop(charge_point_id, None)` is called **inside** the still-held `async with`. The local reference holds the Lock alive for the remainder of the function, but the dict entry is gone.

A concurrent caller for the same `charge_point_id` (e.g., a new WebSocket connection arriving while the heartbeat-monitor's force_disconnect is still running its NR-metric awaits) hits line 110 → finds no entry → creates a **fresh** `asyncio.Lock()` at line 111 → acquires it instantly (no contention with the still-running original) → runs `force_disconnect` in parallel.

Symptoms:
- Duplicate `[DISCONNECT] Force disconnected X` log lines for the same charger within a single second.
- Race on `del self.connected_charge_points[charge_point_id]` (the second caller may find it already deleted; handled).
- Race on `await websocket.close(...)` — both callers can call close on the same (already-closing) WebSocket, producing `RuntimeError: Cannot call "send" once a close message has been sent` (Sentry `OCPP-BACKEND-K`) and `RuntimeError: Unexpected ASGI message 'websocket.send', after sending 'websocket.close'` (Sentry `OCPP-BACKEND-V`).
- Race on the audit log + NR record events — duplicate disconnect events recorded.

This bug is real and observable in staging logs, but it's not the root cause of the 100–190s freezes (those are still under investigation via py-spy). Fixing this removes a confound and stops the duplicate-disconnect log noise.

## What to build

Replace the manual `_cleanup_locks: dict[str, asyncio.Lock]` with `weakref.WeakValueDictionary`. Each `force_disconnect` invocation pins the Lock for the duration of `async with` (via a local strong reference). Concurrent callers for the same charge_point_id see the live Lock and serialize correctly. Once all callers exit, the Lock has no strong references and is garbage-collected automatically — no manual `pop` required.

This is "option (c)" from the original analysis, chosen for simplicity. No behavior change beyond fixing the race.

## What to change

`backend/core/connection_manager.py`:

1. Import `weakref` at the top of the file.
2. Change `self._cleanup_locks: dict[str, asyncio.Lock] = {}` (wherever it's initialized in `__init__`) to `self._cleanup_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()`.
3. In `force_disconnect`:
   - Replace lines 110-113 with:
     ```python
     lock = self._cleanup_locks.get(charge_point_id)
     if lock is None:
         lock = asyncio.Lock()
         self._cleanup_locks[charge_point_id] = lock
     async with lock:
         ...
     ```
     The local `lock` variable is a strong reference — it pins the Lock in the WeakValueDictionary for the duration of `async with`.
   - **Delete line 157** (`self._cleanup_locks.pop(charge_point_id, None)`). The lock is now auto-cleaned by weakref when no one is using it.

The "get-then-create" pattern above has a microscopic TOCTOU window where two callers could each see `lock is None` and both create their own Lock — but the second `self._cleanup_locks[charge_point_id] = lock` overwrites the first, and the first caller holds a strong ref to its own (now-orphaned) Lock. Since asyncio is single-threaded, this only happens if both callers hit those four lines without yielding — which they don't (no awaits between the lookup and the assignment), so it's safe.

If you want belt-and-braces, use `setdefault`:
```python
lock = self._cleanup_locks.setdefault(charge_point_id, asyncio.Lock())
```

But that allocates a Lock per call even on cache hits, which is wasteful. The get-then-create pattern above is cleaner.

## Acceptance criteria

- [ ] `_cleanup_locks` is a `weakref.WeakValueDictionary`.
- [ ] `force_disconnect` uses a local strong reference (`lock = self._cleanup_locks.get(...) or new Lock + assign`) and does `async with lock:`.
- [ ] The manual `self._cleanup_locks.pop(...)` line is removed.
- [ ] Test: simulate concurrent `force_disconnect` calls for the same charge_point_id (e.g., spawn two `asyncio.create_task` invocations on the same id, assert only one disconnect actually fires). The exact assertion shape depends on which side-effects are easy to inspect — perhaps a counter mock on `OCPPMetrics.record_websocket_disconnect`.
- [ ] No more duplicate `[DISCONNECT] Force disconnected X` log lines in staging logs after deploy.
- [ ] Sentry `OCPP-BACKEND-K` and `OCPP-BACKEND-V` decrease in frequency (won't go to zero unless the root-cause freezes are also fixed, but contributions from this race specifically will stop).

## Notes for the agent

Don't touch the `_recently_disconnected` tombstone dict in the same change. It's a separate structure with different lifetime semantics. Keep this PR focused on `_cleanup_locks`.

## Blocked by

None — can start immediately. Independent of all other issues.
