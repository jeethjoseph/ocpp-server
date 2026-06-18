# Prod deploy event — 2026-05-27 (develop → deploy)

## Summary

Bring prod up to current `develop` state. Prod was last deployed on 2026-04-24 (`065460b push to production checkpoint`) — 5 weeks behind. Apply 20 database migrations (23 → 42), provision two new S3 buckets, populate ~15 new env vars, run 3 backfill scripts in sequence.

**RDS prod cutover is a separate event** — see `.scratch/rds-prod-migration/` — and is gated on staging RDS validation closing cleanly (~2026-06-10). This deploy keeps prod's Docker postgres setup unchanged at the connection layer; the new code paths are SSL-aware but `DB_SSL_MODE` stays unset, so behavior falls through to the legacy heuristic.

## Scope

**In scope:**
- Merge `origin/develop` into `origin/deploy` (force-push; project's existing workflow)
- Apply Aerich migrations 23-42 on prod Docker postgres via `aerich upgrade` at container startup
- Create `voltlync-invoices-prod` + `voltlync-firmware-prod` S3 buckets with appropriate CORS + IAM
- Populate ~15 new env vars in `/home/ec2-user/ocpp-server/.env.prod`
- Run 3 backfill scripts: `backfill_gst_schema.py`, `backfill_below_threshold.py`, `reconcile_wallet_balance.py`
- Smoke test the user-visible features that shipped in this batch
- 24-48h observation window before declaring done

**Out of scope:**
- **RDS prod provisioning + cutover** — separate event, gated on staging validation
- New product features beyond what's already on `develop`
- Touching `main` (this deploy is `develop → deploy`)

## Risk shape

| Component | Risk | Mitigation |
|---|---|---|
| 20 sequential migrations | Medium — failures roll back per migration, not as a unit | Pre-deploy backup. Watch logs during `aerich upgrade`. Migration 33 (wallet ledger) is the highest-risk one — has built-in `RAISE NOTICE` output so we'll see drift normalization counts. |
| Mega-commit `4dc6176 "cutover mid"` bundles 5+ unrelated features | Code already in staging since 2026-05-26 with no regressions | Staging signal is strong enough; treat this as the validation |
| S3 bucket misconfig (CORS, IAM) | High — invoice PDFs would fail to upload and fetch | Test with manual PUT/GET via aws cli before deploy; verify CORS policy from a browser fetch |
| Missing env var (especially `VOLTLYNC_GSTIN`) | Silent degradation — invoices skip generation | Pre-deploy checklist; explicit grep on `.env.prod` for all new vars before triggering deploy |
| Backfill script bugs | Data corruption if `--apply` runs on bad input | All three scripts default to dry-run. `--apply` is opt-in. Review dry-run output before commit. |
| Backend image rebuild includes the New Relic agent bump (10.6.0 → 13.0.1) | Low — verified on staging since 2026-05-26 with no issues | None needed |

## Decisions locked

| # | Decision | Why |
|---|---|---|
| 1 | Code deploy this session; **RDS prod cutover deferred** | Bundling them doubles rollback complexity. Staging RDS validation is still in its first day of a 14-day window. |
| 2 | Force-push merge via `make prod-push` (project's existing pattern) | Matches established workflow. No merge-commit ceremony. |
| 3 | Backfills run in dry-run mode first, then `--apply` after human review | All 3 scripts support this. Skipping dry-run is the path to data corruption. |
| 4 | `RAZORPAY_ROUTE_ENABLED=false`, `WALLET_SETTLEMENT_ENABLED=false` for first deploy | These flip on franchisee payouts. Don't activate at the same time as the migration train — separate change after this deploy stabilizes. |
| 5 | Pre-deploy `pg_dump` is the rollback artifact | Same pattern as the staging RDS cutover. Lives on EC2 in `backups/`. |
| 6 | Frontend Sentry/NR Browser env vars are deferred-optional | App works without them; degraded observability only. Don't block the deploy for procurement. |

## Phases

| Phase | Issue | Approx time | Blocks next? |
|---|---|---|---|
| 0 — S3 buckets + IAM | `01-create-prod-s3-buckets.md` | 30 min | Yes (env vars reference them) |
| 0 — Env var procurement + update | `02-populate-prod-env-vars.md` | 30 min – 2 hr (depends on procurement) | Yes (deploy reads these) |
| 0 — Pre-deploy backup | `03-prod-pg-dump-backup.md` | 5 min | Yes (rollback safety net) |
| 1 — Code deploy + migrations | `04-merge-and-deploy.md` | 15-30 min downtime | Yes |
| 1 — Verify backend healthy | `05-post-deploy-verification.md` | 10 min | Yes |
| 2 — GST schema backfill | `06-backfill-gst-schema.md` | 20 min | Yes (touches invoice rows) |
| 2 — Below-threshold backfill | `07-backfill-below-threshold.md` | 10 min | No (orthogonal) |
| 2 — Wallet reconcile validation | `08-reconcile-wallet-balance.md` | 10 min | No (read-only) |
| 3 — Smoke tests + observation | `09-post-deploy-smoke-tests.md` | 24-48h passive | — |

## Rollback paths

| Failure point | Rollback strategy |
|---|---|
| S3 bucket creation fails | Stop. No prod impact yet. |
| Env var update breaks `.env.prod` parsing | `cp .env.prod.pre-deploy-2026-05-27 .env.prod`. Restart only affects already-running container. |
| `make prod-deploy` fails during `aerich upgrade` (most likely on migration 33) | DO NOT re-run. Investigate the specific failure. Possible: restore from pre-deploy `pg_dump`, revert deploy branch to `065460b`, re-deploy old image. ~30 min total. |
| Backend starts but a specific endpoint is broken | Revert just the code: `git push origin 065460b:deploy --force` then `make prod-deploy` again. Postgres schema stays new (migrations are forward-only). Re-test. |
| Backfill `--apply` writes wrong data | If caught quickly: restore affected rows from pre-deploy `pg_dump`. If caught late: case-by-case repair. Dry-run review is the upstream guard. |
| Observation phase surfaces serious issue | Roll code back (as above). If the issue is migration-induced and code-only revert isn't enough, this becomes a major incident. |

## Cost impact

| Item | Approx monthly (USD) |
|---|---|
| S3 `voltlync-invoices-prod` (PDFs, 7-year retention) | ~$1–5 first year, growing |
| S3 `voltlync-firmware-prod` (firmware binaries) | ~$1–2 |
| NR / Sentry already paid | $0 marginal |
| Migration / backfill execution | $0 |
| **Total new** | **~$2-7/mo first year** |

(RDS cost is a separate event — not included here.)

## Issues

Detailed runbooks in `issues/`:

- `01-create-prod-s3-buckets.md` — buckets, CORS, IAM, lifecycle policies
- `02-populate-prod-env-vars.md` — checklist of every var, where to procure each
- `03-prod-pg-dump-backup.md` — rollback artifact
- `04-merge-and-deploy.md` — the actual deploy event
- `05-post-deploy-verification.md` — mechanical health checks + migration verification
- `06-backfill-gst-schema.md` — GST invoice backfill with dry-run gate
- `07-backfill-below-threshold.md` — stuck PENDING settlement entries
- `08-reconcile-wallet-balance.md` — read-only wallet ledger sanity check
- `09-post-deploy-smoke-tests.md` — user-flow verification + 24h observation
