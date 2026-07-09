# `transaction.finalized` audit event can go missing (fire-and-forget not persisted)

Status: done

## What to build

For prod txn 870, the `audit_log` ends at `transaction.resume_blocked`
(10:31:17.923) with **no `transaction.finalized` row**, even though the
`transaction` record shows `STOPPED` with `end_time` 10:31:17.939 (16 ms later).
So the finalize happened, but its audit event did not persist.

`finalize_stopped_transaction` writes the `transaction.finalized` audit via
`safe_create_task(log_audit_event(...))` — fire-and-forget. If that task is
dropped/errors (or loses its DB connection) the audit is silently lost while the
transaction row is still updated. The audit trail is the "supplier of record for
what the system did" (see CONTEXT.md) — a finalize with no audit row is a gap.

Investigate whether the `transaction.finalized` audit write should be awaited (or
retried) rather than fire-and-forget, at least for the finalize transition, so
the audit trail can't diverge from the transaction state. Check whether other
`safe_create_task(log_audit_event(...))` sites have the same exposure.

## Acceptance criteria

- [ ] Root cause understood: why 870's finalize audit didn't persist (dropped task vs error vs cross-loop).
- [ ] Decision recorded: await the finalize-transition audit, or accept fire-and-forget with a rationale.
- [ ] If awaited: `finalize_stopped_transaction` writes `transaction.finalized` synchronously (or with bounded retry); regression test asserts the audit row exists after a finalize.

## Blocked by

None — but low urgency; the `transaction` row remained correct, so no billing/state impact.

## Comments

**Implemented 2026-07-06.** `finalize_stopped_transaction`'s `transaction.finalized` audit write is now **awaited** (was `safe_create_task` fire-and-forget), wrapped in try/except so an audit-insert failure logs a warning but never blocks the finalize. Regression test `test_writes_finalized_audit_event` asserts exactly one `transaction.finalized` row exists after a finalize. Decision on the "why did 870 specifically drop" question: **not root-caused** — 870's runtime context is long gone and unrecoverable, and fire-and-forget is inherently droppable (task GC / swallowed error / loop churn during the charger's flap). The await fix addresses the whole class regardless of the specific 870 cause, which is the right robustness trade for a state-of-record transition. Only the finalize-transition audit was converted; other fire-and-forget audits (metrics, settlement, invoice) left as-is per the ticket's scope-creep note.

Surfaced during the WS-disconnect RCA (2026-07-06). Scope creep risk: don't
convert every fire-and-forget audit to awaited — only the ones where a missing
row would misrepresent a state transition (finalize is the clear one).
