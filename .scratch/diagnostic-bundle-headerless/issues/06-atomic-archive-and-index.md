# Make the S3 archive and the index row succeed or fail together

Status: done

## What to build

`receive_bundle` writes to S3, then inserts the index row. There is no compensation between them, so any insert failure strands an object the retention sweep can never reclaim — it only deletes objects it has rows for. The int32 crash on 2026-08-27 turned that into a generator: 92 objects against 15 rows on a single charger in one morning, one more every ~75 s.

The failure mode is worse than a plain 500. Because `find_duplicate` looks in the database and there is no row, the charger's retry re-archives instead of short-circuiting, so each attempt costs another object and the charger can never advance its delivered marker.

Two candidate orderings:

1. **Index first, archive second** — insert the row with the S3 key it *will* have, then put the object, then mark the row complete. A crash between leaves a row pointing at a missing object, which the sweep can find and clean.
2. **Archive first, compensate on failure** — keep today's order but delete the object if the insert throws.

Prefer (1). Option (2) needs `s3:DeleteObject`, and the IAM policy deliberately withholds it (ADR 0029: "the lifecycle rule expires Bundles and the application can never remove one"). Widening that permission to paper over an ordering bug is the wrong trade.

Whichever lands, the durability contract from ADR 0029 is unchanged and non-negotiable: **no 2xx until the object is durably in S3.** A charger advances its delivered marker on 2xx and may then overwrite those records.

## Acceptance criteria

- [x] An index-write failure leaves no unreferenced S3 object, or leaves one that a documented sweep can identify and remove.
- [x] A 2xx is still returned only after the S3 put has completed.
- [x] An S3 failure still returns 503, with the Sentry capture and `stage` extra intact.
- [x] Test: force the index write to raise and assert no orphan results.
- [x] Test: force the S3 put to raise and assert 503 plus no partial row.
- [x] `docker exec ocpp-backend pytest tests/test_diagnostics_endpoint.py` passes (baseline: 63 passed across the five diagnostics files).

## Blocked by

- None — independent, though cleaner to land after 05

## Comments

**2026-08-27 — implemented, option (1) index-first.** Migration `56_20260827122936_diagnostic_bundle_archived_at`.

Option (2) stayed rejected: compensating after the fact needs `s3:DeleteObject`, which ADR 0029 withholds from the EC2 role on purpose. Widening that grant to paper over an ordering bug is the wrong trade, and the purge in issue 07 was done with local credentials precisely so the role kept its restriction.

**The hazard this introduces, and how it is closed.** Writing the row first means a row can now outlive a missing object — the inverse of the orphan problem. Left alone that is worse, not better: a retry would match the row and get a 2xx for records that reached nowhere, which is the exact failure the durability gate exists to prevent. `archived_at` closes it:

- `find_duplicate` filters `archived_at__isnull=False`. A reservation is invisible to it, so a charger retrying after a failed upload is told to re-send rather than falsely assured.
- `reserve_bundle` **reuses** an existing unarchived row instead of creating a second, so a charger retrying into a broken bucket accumulates one row, not one per attempt.
- `mark_archived` is called only after the S3 put returns, and is what emits the loss signals.
- `stale_reservations(older_than_minutes)` is the documented sweep target.

**Verified against real Postgres** (not asserted against source text — an earlier draft of these tests inspected source strings, which passes even when the logic is wrong):

```
1. first reserve      -> already_archived=False  archived_at=None
2. duplicate check    -> None            (does not claim delivery)
3. retry reserve      -> same row=True   key kept  rows for sha=1
4. stale sweep sees   -> 1 reservation
5. after mark_archived-> duplicate check finds it, archived_at set
6. stale sweep now    -> 0 reservations
```

Unit coverage of the DB-touching functions deliberately lives in that verification rather than in `test_diagnostic_bundle_service.py`, which is DB-free by design (the endpoint tests' docstring records the cross-loop flake that motivates it). The observable that matters is pinned in the endpoint suite: `test_s3_failure_is_not_reported_as_success` now also asserts `mark_archived` was **not** called.

Suite: **77 passed** (79 minus the two source-inspection tests, removed as described above).

**2026-09-08 — reconciled to `done` by tracker audit.** Every acceptance criterion was already ticked in this file; only the `Status:` line was never flipped, so the issue still advertised itself as available work. Hand-verified rather than grep-scored, per `.scratch/tracker-reconciliation/REPORT.md`: Shipped as the prescribed **option 1 (index first)**: `reserve_bundle` → `_archive` → `mark_archived`, with 503 on S3 failure. My first pass grepped for `in_transaction`/`delete_object` and wrongly read the absence as unfinished — the ordering *is* the mechanism, and `s3:DeleteObject` was deliberately never taken.
