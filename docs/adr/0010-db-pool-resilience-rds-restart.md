# Database connection pool is hardened with timeouts so an RDS restart self-heals

The asyncpg pool used by Tortoise is configured (via `backend/db_ssl.py:get_pool_kwargs`, spread into the `credentials` dict of both `database.py` and `tortoise_config.py`) with a **client-side per-query timeout**, **idle-connection recycling**, a **bounded connect timeout**, and **server-side `statement_timeout` + TCP keepalives**. The goal is narrow and specific: when the RDS instance restarts or fails over, the backend must **fail fast and self-heal within seconds**, not hang indefinitely until a human restarts the container.

## Context — the incident (staging, 2026-06-02)

`/admin/chargers` and every other DB-backed admin endpoint hung (nginx `504`/`499`), while `/health` stayed `200`. `py-spy` showed the event loop "idle" with no application frame; RDS CPU was ~4% with a flat connection count; a fresh `pg_stat_activity` probe saw **zero backend sessions** while `ss` showed the backend still holding **5 `ESTAB` sockets** to the RDS IP.

Root cause chain:

1. The single-AZ `db.t4g.micro` staging instance is **memory-starved** (1 GiB; `shared_buffers` ~180 MB + RDS/PI/EM agents + long-lived backend caches → chronic low free memory, swap creeping to ~150 MB/day). When pressure peaks, **AWS force-recovers the instance** (`recovery` event category, ~daily — not a user/API action; confirmed absent from CloudTrail).
2. The recovery **restarts Postgres**, killing all server-side sessions. The asyncpg pool did **not** notice — it kept half-open `ESTAB` sockets to the dead server (Linux TCP keepalive wouldn't fire for ~2h).
3. A request checked out a dead connection, issued its **first query**, and — with **no `command_timeout`** — `await`ed a reply that never came. It hung **forever**. Because the coroutine was suspended, `py-spy dump` couldn't see it (suspended tasks aren't on any thread stack), which is why the loop looked "idle" while requests timed out upstream.

The symptom is deceptive: it looks like a total backend wedge, but the database is healthy and idle — the requests never reach it. The only recovery was a manual `docker compose restart backend`. Without app-level timeouts this recurs on **every** RDS restart/failover/maintenance.

## Decision

`get_pool_kwargs(for_migrations=False)` returns, for the **runtime app pool** (`database.py`):

- `command_timeout=30` — **the core fix.** A query on a half-open socket raises `asyncio.TimeoutError` after 30s instead of hanging forever; asyncpg then discards the bad connection. (There is no clean client-side TCP-keepalive knob in asyncpg, so a per-query timeout is the lever that converts "hang" into "fail fast".)
- `max_inactive_connection_lifetime=180` — idle connections are recycled every 3 min, so a stale one left over from a DB restart is dropped rather than reused (and, incidentally, releases accumulated per-backend cache memory).
- `timeout=10` — bounds connection establishment so a dead/blocked DB fails fast.
- `server_settings.statement_timeout=30000` — server-side cancel of runaway queries (defense-in-depth).
- `server_settings.tcp_keepalives_idle/interval/count` — the **server** reclaims connections from a dead backend in ~90s instead of the ~2h OS default.

The **Aerich variant** (`get_pool_kwargs(for_migrations=True)`, used by `tortoise_config.py`) **omits `command_timeout` and sets `statement_timeout=0`** so long DDL migrations are never aborted.

All values are env-overridable (`DB_COMMAND_TIMEOUT`, `DB_POOL_RECYCLE_SECONDS`, `DB_CONNECT_TIMEOUT`, `DB_POOL_MIN_SIZE`, `DB_POOL_MAX_SIZE`, `DB_STATEMENT_TIMEOUT_MS`) with safe defaults, so no compose/`.env` wiring is required to ship.

Two supporting changes ride with this decision:

- **`docker-entrypoint.sh`** pre-flight DB check got `timeout=float(DB_CONNECT_TIMEOUT, 10)` on its `asyncpg.connect`, so the wait-for-DB loop stays predictable instead of hanging on asyncpg's 60s default during a recovery. This is the **third** DB-connect site in the SSL contract; all three now share bounded connect behavior.
- **`services/data_retention_service.py`** deletes are now **batched** (`_delete_old_in_batches`, 5000 rows/batch) so a large purge stays well under `command_timeout` (and holds shorter locks / less bloat).

## Considered alternatives

- **AWS RDS Proxy** (managed pooler in front of RDS that absorbs failovers/restarts transparently). The cleanest *infrastructure-level* resilience answer and a good future addition for prod once it goes Multi-AZ. Deferred, not rejected: it adds cost + a little latency, and — critically — **a pooler is not a substitute for app-level timeouts**: an app that `await`s a dead socket with no `command_timeout` still hangs. App-level timeouts are the prerequisite regardless, so they go first.
- **PgBouncer** (self-hosted pooler). Solves connection-count/churn, not the dead-socket hang on its own; another moving part to operate. Not needed at current scale.
- **Pgpool-II.** Adds load-balancing / read-write split / replication management — overkill and operationally heavy for a single instance. Rejected.
- **Application-level retry / pool pre-ping.** Tortoise/asyncpg has no built-in pre-acquire ping. A custom retry wrapper is more invasive and still needs a timeout underneath to detect the dead connection. `command_timeout` + idle recycling achieves self-healing with far less code; a retry layer can be added later if the few-failed-requests window proves painful.
- **Just keep restarting the backend manually.** Rejected — it's a pager event on every RDS maintenance/failover and was the actual pain that triggered this.
- **Only right-size the instance (`t4g.micro` → `t4g.small`) and skip app changes.** Rejected as a *sole* fix: right-sizing reduces how *often* RDS recovers (it addresses the memory-pressure cause), but failovers/maintenance reboots still happen, and without app-level timeouts each one still wedges the backend. The two are complementary — see Consequences.

## Consequences

- On the next RDS restart/failover, the blast radius is **at most ~30s of failed requests** (clean `500`s as stale connections error out and get discarded), then automatic recovery — instead of an indefinite wedge needing a manual restart.
- `command_timeout=30` assumes no runtime query legitimately runs longer than 30s. The known long op — data-retention purges — was batched to stay under it. If a future heavy admin report needs longer, raise `DB_COMMAND_TIMEOUT` or run that path on a dedicated connection; do **not** silently remove the timeout.
- Migrations are unaffected: the Aerich path has no `command_timeout` and `statement_timeout=0`.
- This is **separate** from the Redis `socket_timeout` gap (event-loop-hardening issue 06) and the OCPP `cp.call` 30s-timeout / orphaned-response behavior — those share the "no timeout → hang" theme but are different code paths.
- **This change does not reduce how often RDS is recovered.** That is driven by memory pressure on the undersized `t4g.micro` and is addressed separately by right-sizing to `t4g.small` and disabling Performance Insights / Enhanced Monitoring on staging (where, per project convention, PI should not be enabled). Pool resilience makes the reboots *harmless*; right-sizing makes them *stop happening*. Do both.
- A future contributor changing DB connection logic must keep all three connect sites consistent (`database.py`, `tortoise_config.py`, `docker-entrypoint.sh`) — the same rule the SSL contract already imposes.
