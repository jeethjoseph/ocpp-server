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
