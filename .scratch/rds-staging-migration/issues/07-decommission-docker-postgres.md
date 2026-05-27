Status: needs-triage

# Decommission the Docker postgres service on staging

## Status note

This issue is intentionally `needs-triage` (NOT ready-for-agent or ready-for-human). It must remain so until **every** decommission trigger in the PRD is satisfied. Do not promote this issue's status without verifying each trigger in writing.

## What to build

After the 14-day validation window post-cutover, remove the now-dormant Docker postgres service from staging:

1. Remove the `postgres` service block from `docker-compose.staging.yml`
2. Remove `ocpp-postgres-staging` references from the Makefile (or remove the targets that depended on it)
3. After the PR is deployed, run `docker volume rm` on the EC2 host to reclaim the disk space
4. Remove the cutover `backups/staging_cutover_*.sql` artifact (or move to S3 if you want long-term forensics)

## Why this is a SEPARATE PR from the cutover

The cutover PR (issue 05) keeps Docker postgres alive specifically so that rolling back is a 30-second `.env.staging` revert. Bundling decommission with cutover removes the safety net at the worst possible moment — when you've just done a database migration and might still discover edge cases.

## Decommission triggers (ALL must be green)

This issue stays `needs-triage` until every one of these is verified. Record each check with date + initials before promoting status.

- [ ] **Zero RDS-related Sentry exceptions** for 7 consecutive days. Filter: project `ocpp-server`, environment `staging`, level error or above, tag/message matches DB themes (connection, timeout, transaction). Verify on Sentry "Issues" page.
- [ ] **At least one Aerich migration** has run cleanly against RDS during the window. Verify: `git log` shows a migration file added + `aerich upgrade` ran successfully on staging.
- [ ] **At least one OCPP simulator E2E test** passed against RDS, exercising the full Start → MeterValues → Stop cycle.
- [ ] **NR APM p95 latency** within ~10% of pre-cutover baseline. Compare 7-day rolling window before cutover with 7-day rolling window after, on the `OCPP-Server-Staging` entity.
- [ ] **No CloudWatch RDS alarms** triggered. Check: CPU, IOPS, connections, freeable memory, replica lag (N/A for Single-AZ, but enabled for future Multi-AZ).
- [ ] **Backend container restarted at least once** during the window without breaking. Either as part of a normal deploy or as a deliberate test.

## Why this approach over alternatives

| Alternative | Reason rejected |
|---|---|
| Decommission after 7 days | Too aggressive. 14 days catches weekly cron-style anomalies (settlement processing, retention sweeps, billing retries on the 7-day cycle). |
| Decommission after 30 days | Marginal additional safety; just delays the cleanup without proportional benefit. |
| Never decommission; keep Docker postgres as permanent fallback | Disk fills, postgres process consumes RAM unnecessarily, "two source of truth" confusion when someone updates one and not the other. |
| Just stop the container, keep the volume | OK as an intermediate; doesn't reclaim disk. Disk is the eventual scarce resource. |

## What to change (when promoted to ready-for-agent)

### `docker-compose.staging.yml`

```diff
- postgres:
-   image: postgres:15-alpine
-   container_name: ocpp-postgres-staging
-   restart: unless-stopped
-   environment:
-     - POSTGRES_USER=${POSTGRES_USER}
-     - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
-     - POSTGRES_DB=${POSTGRES_DB}
-   volumes:
-     - postgres-data:/var/lib/postgresql/data
-   healthcheck: ...
-
  volumes:
-   postgres-data:
    redis-data:
    ...
```

### `Makefile`

Remove the warn-and-exit `staging-backup-db` / `staging-restore-db` targets (added in issue 03) since they're no longer needed — RDS handles backups and the warning has done its job.

Either remove `staging-db-reset` or rewrite it to use the RDS endpoint with extreme caution (multiple confirmations).

### Post-merge on EC2 host

After PR deploys:

```bash
# Confirm Docker postgres is no longer in the compose stack
$(STAGING_COMPOSE) ps  # should not list postgres

# Reclaim the volume (final destructive step)
sudo docker volume rm ocpp-server_postgres-data
# (volume name may vary; confirm with: sudo docker volume ls)

# Optionally, move the cutover artifact to S3 for long-term forensics
sudo aws s3 cp ~/ocpp-server/backups/staging_cutover_*.sql \
  s3://voltlync-archive/ --profile voltlync
# Then remove the local copy
rm ~/ocpp-server/backups/staging_cutover_*.sql
```

## Verification post-decommission

- `$(STAGING_COMPOSE) ps` does not list `ocpp-postgres-staging`
- `sudo docker volume ls` does not list the postgres data volume
- `df -h /` shows disk usage reduced by the size of the postgres volume (~600 MB-1 GB)
- Backend still functions normally against RDS

## Definition of done

- All decommission triggers verified and recorded
- PR merged and deployed
- Volume removed from EC2 host
- Cutover artifact archived or removed
- This issue's Status moved to a closed state (or the file moved to `issues/done/` if that's the convention you adopt)
