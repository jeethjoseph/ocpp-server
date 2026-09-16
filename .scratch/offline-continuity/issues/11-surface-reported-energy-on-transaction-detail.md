# Surface reported energy beside billed energy on the transaction detail

Status: ready-for-agent

## What to build

Show ops what the charger said it delivered next to what we billed, on the admin transaction detail. The data already exists — issue 01 added `Transaction.reported_end_meter_kwh` and `reported_energy_kwh` (migration 64) — but nothing reads them. Today the only way to see a write-off gap is a SQL query, and the person deciding whether the write-off policy is costing too much needs to see it on the page they already open.

Add the two fields to the admin transaction detail response in `routers/transactions.py` (the detail schema, not the list — the list is bounded per ADR 0025 and this is not a filter axis). On `frontend/app/admin/transactions/[id]/page.tsx`, render **Reported energy** beside **Billed energy**, using exactly those two labels from CONTEXT.md. When the two agree, or when reported is null (a session that never got a stop), show nothing extra. When they differ, show the gap and a short note that the billed figure is final and the reported figure is what the charger later said — do not call either one "actual".

This is read-only display: no edit affordance, no recompute button, no link to a credit note that does not exist. Keep the franchisee portal out of scope — a franchisee sees Settlement Entries, and those are computed from billed energy only.

See ADR 0031 decision 5, the **Reported energy** vs **Billed energy** entry in CONTEXT.md, and issue 01.

## Acceptance criteria

- [ ] Admin transaction detail API returns `reported_end_meter_kwh` and `reported_energy_kwh`
- [ ] The detail page shows Reported energy beside Billed energy only when they differ, with the gap
- [ ] A transaction with no reported figure renders exactly as today
- [ ] Copy does not describe either figure as "actual" and does not imply the billed figure can be corrected
- [ ] `npm run build` and `npm run lint` both clean; the router test asserts the two fields are present
- [ ] Franchisee portal untouched

## Blocked by

None - can start immediately
