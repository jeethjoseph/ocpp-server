"""Shared TLS configuration for the Postgres connection used by both
``database.py`` (runtime) and ``tortoise_config.py`` (Aerich CLI).

The returned value is whatever Tortoise/asyncpg expects in the ``ssl``
credentials key:

- A string like ``"disable"`` / ``"require"`` for built-in modes
- An ``ssl.SSLContext`` for verify-ca / verify-full (so a custom CA
  bundle can be loaded)

Env-var contract:

- ``DB_SSL_MODE`` — one of ``disable``, ``allow``, ``prefer``, ``require``,
  ``verify-ca``, ``verify-full``. Empty/unset falls back to the legacy
  "disable on local, require on cloud" heuristic so local dev keeps working
  without any new env wiring.
- ``DB_SSL_CA_PATH`` — path to the CA bundle used for verify-ca/verify-full.
  Defaults to ``/etc/ssl/rds-ca-bundle.pem`` which is baked into the image
  by ``Dockerfile``.
"""
import os
import ssl

LOCAL_HOSTS = {"localhost", "127.0.0.1", "postgres"}
DEFAULT_CA_PATH = "/etc/ssl/rds-ca-bundle.pem"


def get_ssl_config():
    """Return the value to put in Tortoise credentials ``ssl`` key."""
    mode = os.getenv("DB_SSL_MODE", "").strip().lower()
    host = os.getenv("DB_HOST", "localhost")
    is_local = host in LOCAL_HOSTS

    if mode in ("verify-ca", "verify-full"):
        ca_path = os.getenv("DB_SSL_CA_PATH", DEFAULT_CA_PATH)
        ctx = ssl.create_default_context(cafile=ca_path)
        ctx.verify_mode = ssl.CERT_REQUIRED
        if mode == "verify-ca":
            # Validate the cert chain but allow hostname mismatches. Rare;
            # mostly here for completeness.
            ctx.check_hostname = False
        return ctx

    if mode:
        # Explicit non-verify mode passes through to asyncpg unchanged.
        return mode

    # No DB_SSL_MODE set — preserve the legacy fallback so existing
    # local-dev and pre-migration staging keep working.
    return "disable" if is_local else "require"


def get_pool_kwargs(*, for_migrations: bool = False) -> dict:
    """asyncpg pool-resilience kwargs, passed via Tortoise's ``credentials`` dict.

    Tortoise consumes ``minsize``/``maxsize``/``server_settings`` and forwards
    everything else to ``asyncpg.create_pool`` (as per-connection connect kwargs).

    These guard the RDS-restart stale-pool wedge: after the DB restarts/fails
    over, the pool can keep half-open sockets, and with no timeout a query on
    one hangs forever (TCP keepalive won't fire for ~2h). ``command_timeout``
    turns that hang into a fast error; idle connections are recycled so stale
    ones are dropped.
    """
    server_settings = {
        # Server-side cancel of runaway queries (ms; 0 = disabled for migrations
        # which legitimately run long DDL).
        "statement_timeout": os.getenv(
            "DB_STATEMENT_TIMEOUT_MS", "0" if for_migrations else "30000"
        ),
        # Server-side TCP keepalive: reclaim connections from a dead backend in
        # ~90s instead of the ~2h OS default.
        "tcp_keepalives_idle": "60",
        "tcp_keepalives_interval": "10",
        "tcp_keepalives_count": "3",
        "application_name": "ocpp-aerich" if for_migrations else "ocpp-backend",
    }
    kwargs = {
        "minsize": int(os.getenv("DB_POOL_MIN_SIZE", "1")),
        "maxsize": int(os.getenv("DB_POOL_MAX_SIZE", "10")),
        # Recycle idle connections so a post-restart stale one is dropped, not reused.
        "max_inactive_connection_lifetime": float(
            os.getenv("DB_POOL_RECYCLE_SECONDS", "180")
        ),
        # Bound connection establishment so a dead/blocked DB fails fast.
        "timeout": float(os.getenv("DB_CONNECT_TIMEOUT", "10")),
        "server_settings": server_settings,
    }
    if not for_migrations:
        # The core fix: per-query client-side timeout. A query on a half-open
        # socket raises asyncio.TimeoutError instead of hanging indefinitely.
        kwargs["command_timeout"] = float(os.getenv("DB_COMMAND_TIMEOUT", "30"))
    return kwargs
