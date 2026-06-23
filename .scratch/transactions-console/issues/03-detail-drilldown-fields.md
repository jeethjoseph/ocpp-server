# Transactions Console — drill-down to session detail with payment + settlement status

Status: ready-for-agent
Type: AFK

## What to build

Make Transactions Console rows drill into the **existing** session-detail view (backed by `GET /transactions/{id}`, already reused on the charger detail page) — reuse it, do not build a parallel detail page. Add two **read-only** fields to that detail view:

- **Payment Status** — the verbatim native status of the backing payment record (same truthful value as the list column from slice 02).
- **Settlement Status** — the `SettlementStatusEnum` of the session's `CommissionLedgerEntry` (franchisee payout state), read-only.

Settlement status is intentionally **detail-only** — it is NOT a list filter axis. Payout triage keeps its own home at `/admin/settlements`; this is just a convenience readout so an admin viewing a session can see "did the franchisee get paid" without leaving. Run the frontend production build.

## Acceptance criteria

- [ ] Clicking a console row opens the existing session-detail view (reused, not duplicated)
- [ ] Detail view shows read-only Payment Status (native value) and Settlement Status (`SettlementStatusEnum`)
- [ ] Settlement status appears ONLY on detail — not added as a list column or filter
- [ ] Sessions with no settlement entry / no payment record render gracefully (empty, not error)
- [ ] `cd frontend && npm run build` passes

## Blocked by

- `.scratch/transactions-console/issues/01-console-page-mvp.md`

## Comments

- **2026-06-20 — Implemented.** GET /transactions/{id} adds read-only payment_status + settlement_status; new /admin/transactions/[id] detail page renders both (null → —). Settlement kept off the list. Tests + build green.
