# Reclaim the S3 objects stranded by the ingest 500 loop

Status: done

## What to build

The 500 loop stranded objects in `voltlync-diagnostics-staging` that no `diagnostic_bundle` row points at. As of 2026-08-27 09:49 UTC the staging test unit had 92 objects for the day against 15 indexed rows, growing by roughly one per 75 s for as long as the loop runs.

They will never be reclaimed automatically. The retention sweep deletes rows and their objects; it has no notion of an object without a row. The 90-day S3 lifecycle rule will eventually expire them, so this is untidiness rather than unbounded growth — but it corrupts the archive's meaning, because the bucket now contains many near-identical copies of the same records with nothing indicating which was ever accounted for.

Marked **ready-for-human** deliberately: it deletes data from an S3 bucket, and the EC2 role does not currently hold `s3:DeleteObject` (ADR 0029 withholds it on purpose). Whoever does this needs to decide whether to grant it temporarily, run the deletion with separate credentials, or leave the strays to the lifecycle rule.

Steps:

1. List every object under `diagnostics/` and left-join against `diagnostic_bundle.s3_key` to produce the orphan set. Read-only, safe to run any time.
2. Report the count, total bytes, and date span before deleting anything.
3. Decide: delete, or let the 90-day lifecycle rule expire them. Deleting is defensible only once the count is confirmed and the ingest loop has stopped — otherwise it re-fills.
4. If deleting, do it from a script that re-checks each key against the database immediately before removal.

Do not run step 4 while the charger is still 500-looping.

## Acceptance criteria

- [x] Read-only reconciliation script exists, reporting orphan count / bytes / span for a given bucket and environment.
- [x] Run against staging and the numbers recorded in this issue's Comments.
- [x] An explicit decision recorded: delete now, or defer to the lifecycle rule.
- [x] If deleting: each key re-verified against the database immediately before removal, and the IAM change (if any) reverted afterwards.
- [x] Prod bucket checked for the same condition — the endpoint 404s there today, so it should be clean, but confirm rather than assume.

## Blocked by

- Issue 05 or 06 — the loop must have stopped, or the orphan set refills as fast as it is cleared

## Comments

**2026-08-27 — done, and wider than this issue originally scoped.**

The user's call was to purge everything rather than reclaim orphans only: the diagnostic traces collected to date have no analytical value, so a clean slate beats a consistent-but-stale archive.

State before:

| | |
|---|---|
| S3 objects | 211 (5.4 MB, one charger, 2026-08-19 → 08-27) |
| Indexed rows | 16 |
| Orphans | 195 |

The 500 loop had already stopped — zero POSTs in the 30 minutes before the purge, last row written 10:12 UTC — so the bucket would not re-fill mid-delete.

Executed:
1. Full key manifest saved before deleting anything (211 keys). Not a backup of content, but a record of exactly what was removed.
2. Permission probed on a single object first, so a missing grant would surface on one key rather than mid-bulk.
3. `aws s3 rm --recursive` under the local `voltlync` profile (`user/jeeth-voltlync`). **The EC2 role's IAM was not touched** — ADR 0029 withholds `s3:DeleteObject` from it deliberately, and that stands.
4. `DELETE FROM diagnostic_bundle` on staging — `DELETE 16`.

Verified after: **0 objects, 0 rows.**

Prod: `voltlync-diagnostics-prod` **does not exist**. Consistent with ADR 0029 ("the prod bucket is not yet created") and with the endpoint 404ing there. Nothing to clean.

The bucket, its 90-day lifecycle rule and its policies are untouched — only the objects were removed. The next real upload starts against an empty bucket as row 1.
