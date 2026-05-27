Status: ready-for-agent

# Update docs + auto-memories to reflect the staging-RDS reality

## What to build

Post-cutover, several files describe the system as if all envs use Docker postgres. They're now wrong for staging and need updating. This issue captures the textual changes; can land as a separate small PR within ~24 hours after cutover.

## Why this approach over alternatives

| Alternative | Reason rejected |
|---|---|
| Create new memory files for the RDS-specific patterns | More memory bloat; future readers might miss one. Single-source-of-truth per topic is better. |
| Defer all doc updates until prod also migrates | Asymmetry will exist for weeks; un-updated docs become an AI/human trap during that window. |
| Delete the Docker postgres patterns from memories | Prod still uses Docker postgres. Removing the patterns breaks prod operations. Better: have both, clearly labeled. |

## What to change

### `memory/reference_aws_ssm_protocol.md`

Add a heading split before the existing "Postgres query" section:

```markdown
### Postgres query — staging (RDS, post-2026-MM-DD)

Use the new Makefile target for interactive shell:
  make staging-rds-shell

For one-off SQL via SSM (the backend container has connection env vars set):
  sudo docker exec ocpp-backend-staging sh -c \
    'PGPASSWORD=$POSTGRES_PASSWORD psql -h $POSTGRES_HOST -U $POSTGRES_USER -d $POSTGRES_DB -c "<SQL>"'

Direct psql from EC2 host (requires aws RDS CA bundle for verify-full):
  curl -fsSL https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem -o /tmp/rds-ca.pem
  PGPASSWORD='<from .env.staging>' psql \
    "host=ocpp-staging-db.cXXXXXXX.ap-south-1.rds.amazonaws.com \
     user=ocpp_staging dbname=ocpp_staging_db \
     sslmode=verify-full sslrootcert=/tmp/rds-ca.pem" \
    -c "<SQL>"

### Postgres query — prod (still Docker, pre-migration)

sudo docker exec ocpp-postgres-prod psql -U ocpp_prod -d ocpp_prod_db -c "<SQL>"
```

Replace the actual `cXXXXXXX` placeholder with the live endpoint hostname after cutover.

### `memory/feedback_stop_before_handwriting_migration.md`

The technique still applies (pull a state from staging when local aerich is stuck), but the "via SSM" step needs to know it's hitting RDS for staging now. Add a one-line note pointing to the new pattern in `reference_aws_ssm_protocol.md`.

### `CLAUDE.md`

Add a new section after the existing env-var checklist:

```markdown
## Database tier

- **Local dev**: Docker postgres (in `docker-compose.yml`). No change from established pattern.
- **Staging**: AWS RDS Postgres `ocpp-staging-db.cXXXXXXX.ap-south-1.rds.amazonaws.com`.
  Single-AZ db.t4g.micro in ap-south-1. Automated backups + PITR (14 days). Connection
  requires `POSTGRES_SSL_MODE=verify-full` with the AWS RDS CA bundle baked into the
  backend image at `/etc/ssl/rds-ca-bundle.pem`.
- **Prod**: Docker postgres (pending migration; separate future project).

For ad-hoc staging psql: `make staging-rds-shell`.
For prod: same as before — `docker exec ocpp-postgres-prod psql ...`.
```

### `docs/v1/llm-context-document.md`

Append a line in the Environments section (or create one if it doesn't exist):

```markdown
- **Staging DB**: AWS RDS Postgres (since 2026-MM-DD). Endpoint
  `ocpp-staging-db.cXXXXXXX.ap-south-1.rds.amazonaws.com`. Single-AZ db.t4g.micro,
  14-day backup retention, PITR enabled. Migrated from Docker postgres
  per the RDS staging migration project; see `.scratch/rds-staging-migration/PRD.md`.
```

### `docs/v1/comprehensive-architecture-documentation.md`

Append a section near the database / deployment description:

```markdown
## Database tier (post-2026-MM-DD)

The staging environment uses AWS RDS Postgres; production still uses Docker
postgres pending a separate migration. The two environments are intentionally
asymmetric during the prod-migration runway.

Staging RDS specifics:
- Engine: Postgres 15.x, instance `db.t4g.micro` Single-AZ in ap-south-1
- Storage: 20GB gp3 with auto-scaling up to 100GB
- Backup retention: 14 days with PITR (5-minute granularity)
- Connection: `POSTGRES_SSL_MODE=verify-full` with the AWS global RDS CA bundle
  baked into the backend image during `docker build`
- Master user `ocpp_admin` is used only for one-time setup and rare admin tasks;
  the backend connects as the unprivileged `ocpp_staging` app user
- Decommission of the local Docker postgres on staging happens via a separate
  PR after a 14-day validation window; see issue 07 in
  `.scratch/rds-staging-migration/issues/`

Production retains the Docker postgres pattern documented in
`reference_aws_ssm_protocol.md` until a future migration project.
```

## Verification

- `grep "ocpp-postgres-staging" memory/*.md` should return zero results outside of historical-context blocks (everything live should point at the RDS pattern for staging)
- `make staging-rds-shell` works against the live staging RDS
- Reading the docs without prior context should make the staging-vs-prod asymmetry obvious

## Definition of done

- All 5 files updated with the changes above
- Live endpoint hostname substituted for `cXXXXXXX` placeholders
- Cutover date substituted for `MM-DD` placeholders
- PR merged to `develop`
