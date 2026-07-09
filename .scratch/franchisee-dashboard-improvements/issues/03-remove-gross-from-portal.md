# 03 — Remove Gross from the franchise portal

Status: ready-for-agent

## What to build

Stop surfacing platform **Gross** anywhere in the franchisee portal, and replace the settlement table's Gross column with **Power Consumed (kWh)**, per the CONTEXT.md Settlement Entry term. A franchisee should see Payout, TDS, commission %, and energy — never platform Gross.

- **Settlement history table**: replace the **Gross** column with **Power Consumed (kWh)**, rendering `energy_consumed_kwh` (already returned by the endpoint — no new data).
- **Settlement summary**: drop the **`total_gross`** card.
- **Backend**: remove `gross_amount` (per row) and `total_gross` (summary) from the franchisee settlements endpoint response. Leave `franchisee_payout`, `commission_percent`, `platform_commission`, `tds_amount` intact. The `CommissionLedgerEntry` row still stores `gross_amount` — only the franchisee-facing response drops it.

## Acceptance criteria

- [ ] Settlement table shows Power Consumed (kWh) where Gross used to be
- [ ] The `total_gross` summary card is gone
- [ ] Franchisee settlements endpoint no longer returns `gross_amount` / `total_gross`
- [ ] Payout, TDS, and commission % remain visible
- [ ] No "Gross" string remains on any franchisee-facing surface (table, summary, and — once built — graphs/exports)
- [ ] Per-file pytest asserts the franchisee settlements response omits gross fields
- [ ] `cd frontend && npm run build` passes

## Blocked by

- None - can start immediately
