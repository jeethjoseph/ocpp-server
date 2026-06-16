# Bound the graceful-close wait in `force_disconnect` so a dead cellular socket can't stall connection takeover

Status: ready-for-agent

## Problem

Every charger disconnect we observe is WebSocket close code **1006** (abnormal closure, no close handshake) — the cellular/Quectel modem TCP connection vanishes and the server only notices on the next read. See the 48h log evaluation (2026-06-15): 100% of natural disconnects on both staging and prod are 1006; zero clean 1000/1001 closes.

In the **stale-connection replacement** path (`routers/ocpp_ws.py:63` → `force_disconnect`), the server frequently still has the old socket marked `CONNECTED` when the charger's *new* TCP connection arrives. `force_disconnect` then calls:

```python
# backend/core/connection_manager.py:138-140
if self.is_ws_connected(websocket):
    await websocket.close(code=1001, reason=f"Server cleanup: {reason}")
    logger.info(f"[DISCONNECT] Sent WebSocket close frame to {charge_point_id}: {reason}")
```

Because the peer is already gone (1006), `await websocket.close()` blocks waiting for a close-ACK that never comes, until Starlette's internal close timeout fires. In the logs this shows as a **~10-second gap** between `Cancelled heartbeat task` and `Sent WebSocket close frame`. The `force_disconnect` lock (`connection_manager.py:123`) is held for that whole window, so the **new** connection's takeover is stalled ~10s.

Prod exercises this far more than staging:

| | Staging (48h) | Prod (48h) |
|---|---|---|
| Stale-connection replacements | 3 (12% of disconnects) | **6 (46% of disconnects)** |
| `CONNECTED` state at disconnect (close race) | 0 | 2 |

Prod chargers reconnect faster than the server detects the dead socket, so nearly half of prod disconnects pay the 10s stall. The related `"Cannot call send once a close message has been sent"` warning (caught at `:144-148`) is the same root cause surfacing as a race and is cosmetic — this issue is about the **blocking wait**, not that log line.

## What to build

Bound the graceful close so it can never hold the lock for more than ~1s on a dead socket. Attempting a graceful 1001 close frame on a peer that closed with 1006 is near-useless; we should try briefly, then fall through to the transport close that `:146-147` already does.

### Plan

- In `force_disconnect` (`backend/core/connection_manager.py:137-148`), wrap the graceful close in `asyncio.wait_for(websocket.close(...), timeout=CLOSE_GRACE_SECONDS)` with `CLOSE_GRACE_SECONDS = 1.0` as a module constant.
- On `asyncio.TimeoutError` (or any exception), log at INFO/DEBUG (not WARNING — this is expected for 1006 peers) and fall through to the existing forced-TCP-closure branch (`websocket._transport.close()` at `:146-147`).
- Keep the `is_ws_connected` guard — if the socket is already `DISCONNECTED` (the common 11/13 prod, 24/24 staging case), behavior is unchanged: it logs `already closed` and skips the close entirely. Only the `CONNECTED`-but-dead path changes.
- Do not change the natural-disconnect path semantics, the tombstone logic (`:155-158`), or the disconnect callbacks (`:171-173`). This is purely about bounding step 2.

### Why not just skip the close on the stale-replacement path?

We could special-case `reason == "New connection attempt - replacing stale connection"` and skip straight to transport close, but a timeout-bounded `close()` fixes the stall for *all* callers (including future ones) without coupling cleanup logic to a reason string. Prefer the timeout.

## Acceptance criteria

- [ ] `force_disconnect`'s graceful-close call is bounded by `asyncio.wait_for` with a module-level `CLOSE_GRACE_SECONDS = 1.0`.
- [ ] On timeout, the code falls through to forced transport closure and the lock is released within ~1s, not ~10s.
- [ ] The expected-timeout case logs below WARNING (no new noise for routine 1006 disconnects).
- [ ] Already-`DISCONNECTED` sockets still short-circuit via `is_ws_connected` with no behavior change.
- [ ] A unit test simulates a `websocket.close()` that hangs and asserts `force_disconnect` returns within the grace window and still performs state cleanup (`connected_charge_points` entry removed, tombstone set).
- [ ] `docker exec ocpp-backend pytest` for the connection-manager tests passes.

## How to verify on staging after deploy

Re-run the stale-replacement scan and confirm the gap between `Cancelled heartbeat task` and `Sent WebSocket close frame` / `Forced TCP closure` drops from ~10s to ~1s:

```
sudo docker logs ocpp-backend-staging --since 24h 2>&1 | grep -E "replacing stale connection|Sent WebSocket close frame|Forced TCP closure"
```

## Blocked by

None — self-contained change in `backend/core/connection_manager.py` plus a test.

## Notes / non-goals

- **Not** changing the 1006-everywhere reality — that's the documented Quectel modem limitation (`project_quectel_ws_firmware_limitation`), not fixable server-side.
- **Not** addressing the `"Cannot call send once a close message has been sent"` warning beyond letting it fall into the bounded path; it's benign.
- No migration, no env var, no compose change.
