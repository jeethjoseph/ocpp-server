Status: ready-for-agent

# Compose + .env.staging.example + Makefile changes for RDS readiness

## What to build

The infrastructure config changes that let staging point at RDS without breaking anything if `POSTGRES_HOST` is not yet pointing at the RDS endpoint. Safe to merge before the actual cutover.

Specifically:

1. Remove `depends_on: postgres` from the `backend` service in `docker-compose.staging.yml`
2. Add `POSTGRES_SSL_MODE` to the backend environment block
3. Document new env vars in `.env.staging.example`
4. Add a `staging-rds-shell` Makefile target
5. Rewrite `staging-backup-db` and `staging-restore-db` as warn-and-exit (with clear instructions)
6. Keep the Docker `postgres` service in `docker-compose.staging.yml` for now (the validation-window rollback target)

## Why this approach over alternatives

| Alternative | Reason rejected |
|---|---|
| Remove `postgres` service from compose immediately | Loses the rollback safety net during the 14-day validation window |
| Delete `staging-backup-db` outright | Future-you (or AI) will type the old command, get a confusing "no rule" error, waste 10 min figuring out the new model. Warn-and-exit is self-documenting. |
| Hardcode `POSTGRES_HOST` to the RDS endpoint in compose | Breaks rollback. The hostname must come from `.env.staging` so we can flip it back to `postgres` in 30 sec. |
| Add SSL params via compose env (not just `POSTGRES_SSL_MODE`) | Less flexible; backend code already builds the DSN from components. Stick with the helper from issue 02. |

## What to change

### `docker-compose.staging.yml`

In the `backend` service block, remove the `depends_on` reference to postgres:

```diff
 backend:
   build: ./backend
   container_name: ocpp-backend-staging
-  depends_on:
-    - postgres
-    - redis
+  depends_on:
+    - redis
```

(Keep `redis` — backend still depends on it locally.)

In the `backend.environment:` block, add:

```yaml
- POSTGRES_SSL_MODE=${POSTGRES_SSL_MODE:-}
```

The `:-` default keeps behavior identical when the env var isn't set, until cutover sets it.

**Do NOT remove the `postgres` service block.** It stays until the decommission PR (issue 07).

### `.env.staging.example`

Add documentation block near the `POSTGRES_*` section:

```bash
# Postgres connection
# Local Docker postgres (pre-RDS-migration): POSTGRES_HOST=postgres
# AWS RDS (post-migration): POSTGRES_HOST=ocpp-staging-db.cXXXXXXX.ap-south-1.rds.amazonaws.com
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_USER=ocpp_staging
POSTGRES_PASSWORD=replace-me
POSTGRES_DB=ocpp_staging_db

# TLS mode for Postgres connection.
# - Unset/empty: no TLS (Docker postgres on local network)
# - verify-full: TLS with certificate validation (RDS)
# Requires /etc/ssl/rds-ca-bundle.pem in the backend image (baked during build).
POSTGRES_SSL_MODE=
```

### `Makefile`

Add the new `staging-rds-shell` target:

```makefile
# Open a psql shell against the staging RDS instance.
# Reads connection params from the backend container's env so the secret
# doesn't have to leave .env.staging.
staging-rds-shell:
	@if [ -z "$$($(STAGING_COMPOSE) ps -q backend)" ]; then \
		echo "ERROR: backend container not running. Run 'make staging-up' first."; \
		exit 1; \
	fi
	$(STAGING_COMPOSE) exec backend sh -c \
		'PGPASSWORD=$$POSTGRES_PASSWORD psql -h $$POSTGRES_HOST -U $$POSTGRES_USER -d $$POSTGRES_DB'
```

Rewrite the existing `staging-backup-db` target as warn-and-exit:

```makefile
staging-backup-db:
	@echo "============================================================"
	@echo "RDS handles backups automatically:"
	@echo "  - Daily automated snapshots (14-day retention)"
	@echo "  - Point-in-time recovery to any second in the window"
	@echo ""
	@echo "View snapshots: AWS Console -> RDS -> ocpp-staging-db -> Maintenance & backups"
	@echo "PITR restore:   AWS Console -> RDS -> ocpp-staging-db -> Actions -> Restore"
	@echo ""
	@echo "For ad-hoc psql access, use: make staging-rds-shell"
	@echo "============================================================"
	@exit 1
```

Rewrite `staging-restore-db` similarly. The exit code 1 makes it un-pipeable into other commands by accident.

### `staging-db-reset`

This target is now more dangerous because it drops the **RDS** database, not a docker volume. Add an extra confirmation prompt with the actual hostname:

```makefile
staging-db-reset:
	@echo "WARNING: This drops the STAGING RDS DATABASE."
	@echo "Target host: $$(grep ^POSTGRES_HOST .env.staging | cut -d= -f2)"
	@echo "Type 'reset staging db' to confirm, anything else to abort:"
	@read confirm; [ "$$confirm" = "reset staging db" ] || (echo "Aborted."; exit 1)
	# ... rest of existing logic, but using RDS endpoint ...
```

## Verification

Before merging:

1. `docker compose -f docker-compose.staging.yml config` — validates YAML parses
2. The `backend.depends_on` block lists `redis` only (or is absent if redis was the only other entry)
3. `make staging-backup-db` (run locally in dry-run) prints the warn message and exits 1
4. `make staging-rds-shell` (run locally) fails with the "backend container not running" message (unless you have staging compose up locally)

## Definition of done

- PR merged to `develop`
- Staging deploy still works (`make staging-deploy` succeeds — no behavioral change yet because `POSTGRES_HOST` is still `postgres` in `.env.staging`)
- Behavior is identical to pre-PR until the cutover updates `.env.staging` on the EC2 host
