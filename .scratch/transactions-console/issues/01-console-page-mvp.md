# Transactions Console MVP — fix the dead /admin/transactions link

Status: ready-for-agent
Type: AFK

## What to build

Build the admin **Transactions Console** at `/admin/transactions` — the page the long-dead "Transaction Monitoring" landing-card link has always pointed to but never existed. It is a convenience/triage view over **Charging Sessions** (the `Transaction` model is the spine), NOT a money ledger or a super-feed of payments/refunds/settlements (that scope was explicitly rejected — see the **Transactions Console** entry in `CONTEXT.md`).

This MVP slice wires the page to the **already-existing** `GET /transactions` endpoint (pagination, `status`/`user_id`/`charger_id`/date filters, sorting, summary block — all present today; no backend change in this slice). Render a table of all Charging Sessions across all statuses with the **Session Status** (`TransactionStatusEnum`) column, energy, cost, timestamps; expose the session-status and date filters and pagination already supported by the endpoint. Fix the dead landing-card link so it resolves to this page. Match the existing admin pages' table/filter conventions (e.g. `/admin/chargers`, `/admin/users`).

After any `frontend/` edit, run `cd frontend && npm run build` (full production build) per project convention.

## Acceptance criteria

- [ ] `/admin/transactions` page exists and lists Charging Sessions across all statuses via the existing `GET /transactions` endpoint
- [ ] The landing-page "Transaction Monitoring" card link resolves to the new page (no longer dead)
- [ ] Session Status filter, date filters, sorting, and pagination work against the existing endpoint params
- [ ] Summary block (active/suspended/completed counts, total energy) from the endpoint is surfaced
- [ ] No backend endpoint changes in this slice
- [ ] `cd frontend && npm run build` passes

## Blocked by

None - can start immediately

## Comments

- **2026-06-20 — Implemented.** Page /admin/transactions built; dead landing link now resolves. Wired to existing GET /transactions. Build green (exit 0).
