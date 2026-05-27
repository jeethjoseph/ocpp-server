Status: ready-for-agent

# Backend: bake RDS CA bundle into image, add SSL-aware DSN construction

## What to build

Make the backend transparently connect to either Docker postgres (local dev) or AWS RDS (staging/prod) based on the `POSTGRES_HOST` env var. Specifically:

1. Bake the AWS RDS global CA bundle into the backend Docker image at `/etc/ssl/rds-ca-bundle.pem`
2. Update `backend/database.py` and `backend/tortoise_config.py` to append SSL params to the DSN when `POSTGRES_SSL_MODE` is set
3. Keep local dev unchanged (when `POSTGRES_SSL_MODE` is unset/empty, no SSL params are appended)

This change is **safe to merge before cutover** — without `POSTGRES_SSL_MODE` set in any env, behavior is identical to today.

## Why this approach over alternatives

| Alternative | Reason rejected |
|---|---|
| `sslmode=require` (no cert verification) | Encrypts wire but accepts any cert — vulnerable to active MITM. `verify-full` closes this for ~10 min of setup. |
| Download CA bundle at container startup | Adds a network dependency on `truststore.pki.rds.amazonaws.com` being reachable at boot. Image-baked is more reliable. |
| Mount CA bundle via Docker volume | One more thing to remember per env. Image-baked = zero env-specific config for this. |
| Hardcode SSL params in the connection string | Couples the app to one connection mode. Conditional via env var keeps local dev simple. |

## What to change

### `backend/Dockerfile`

Add a step in the builder/runtime stage that downloads the AWS RDS global CA bundle:

```dockerfile
# After base image setup, before COPY of app code:
RUN apk add --no-cache curl \
    && curl -fsSL https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem \
       -o /etc/ssl/rds-ca-bundle.pem \
    && chmod 644 /etc/ssl/rds-ca-bundle.pem
```

(Or `apt-get install` + `curl` if the base image is Debian-derived; check current `backend/Dockerfile` for which family.)

### `backend/database.py`

The DSN-building code reads `POSTGRES_HOST`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_PORT` from env and constructs a URL. Add SSL handling:

```python
import os

def _build_dsn() -> str:
    host = os.getenv("POSTGRES_HOST", "postgres")
    port = os.getenv("POSTGRES_PORT", "5432")
    user = os.getenv("POSTGRES_USER", "ocpp")
    password = os.getenv("POSTGRES_PASSWORD", "")
    db = os.getenv("POSTGRES_DB", "ocpp")
    base = f"postgres://{user}:{password}@{host}:{port}/{db}"

    ssl_mode = os.getenv("POSTGRES_SSL_MODE", "").strip()
    if ssl_mode:
        ca_path = os.getenv(
            "POSTGRES_SSL_CA_PATH", "/etc/ssl/rds-ca-bundle.pem"
        )
        return f"{base}?sslmode={ssl_mode}&sslrootcert={ca_path}"
    return base
```

Use `_build_dsn()` wherever the connection string is constructed today. Keep the existing code path (no SSL) as the fallback when `POSTGRES_SSL_MODE` is unset.

### `backend/tortoise_config.py`

Aerich reads this file to get its connection. Mirror the same SSL logic. If the file currently builds a `db_url` from individual env vars, route it through the same `_build_dsn()` helper (import from `database.py` or duplicate the small function).

If `tortoise_config.py` already takes a full DSN from a single env var (`DATABASE_URL` or similar), you can either:
- (a) Compose the DSN in the env var itself (move SSL append logic to `.env.staging`)
- (b) Have `tortoise_config.py` re-build the DSN from the components

(b) is cleaner because env vars are the same; app builds the DSN consistently in one place.

### Local dev (`docker-compose.yml`)

No change. `POSTGRES_HOST=postgres` and `POSTGRES_SSL_MODE` is unset → no SSL params → existing behavior.

### Tests

No change required. Tests connect via the same DSN logic; without `POSTGRES_SSL_MODE` set in the test env, they're SSL-free as today.

## Verification

Before merging this issue's PR:

1. **Local dev still works**: `docker compose up backend` succeeds against the local Docker postgres without setting any new env vars
2. **CA bundle is in the image**: `docker exec ocpp-backend ls -l /etc/ssl/rds-ca-bundle.pem` shows the file
3. **DSN built correctly with SSL**: Add a temporary `print(_build_dsn())` (and remove before commit), set `POSTGRES_HOST=fake.rds.amazonaws.com` and `POSTGRES_SSL_MODE=verify-full`, see the DSN includes the `?sslmode=...&sslrootcert=...` suffix
4. **Tests pass**: `docker exec ocpp-backend pytest tests/` — at least the test files we know are not flaky (per CLAUDE.md baseline)

## Definition of done

- `backend/Dockerfile` includes the CA bundle download
- `backend/database.py` and `backend/tortoise_config.py` use the new SSL-aware DSN builder
- Local dev verified working with no new env vars set
- PR merged to `develop`
- No changes to behavior in either staging or prod (because neither has `POSTGRES_SSL_MODE` set yet)
