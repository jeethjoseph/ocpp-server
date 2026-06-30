# Wallet de-minimis energy waiver (< 0.5 kWh → no debit, no bill)

Status: ready-for-agent
Type: AFK

## What to build

Apply the **De-minimis Session** waiver symmetrically to the **Wallet Session** billing path. A wallet-funded session that delivered `0 < energy_consumed_kwh < 0.5 kWh` results in **no wallet debit, no GST Invoice, and no Settlement Entry** — the session is marked COMPLETED exactly as a zero-energy wallet session is today.

Mechanically this widens the existing wallet billing guard from `energy ≤ 0` to `energy < MIN_BILLABLE_ENERGY_KWH`, consuming the shared constant introduced in slice 01 (single source of truth — do not redefine it). Same cliff semantics: a wallet session at or above 0.5 kWh bills for its **total** energy.

The waiver is a property of the *supply*, not the funding source — keeping QR and wallet symmetric is the whole reason this slice exists, so a customer's bill never depends on card-vs-QR for the same 0.3 kWh. See ADR 0013 and the **Non-billable Session** glossary entry. Ship tests per project convention (a wallet simulator scenario if one exists for the billing path).

## Acceptance criteria

- [ ] Wallet billing imports and uses the `MIN_BILLABLE_ENERGY_KWH` constant from slice 01 (not a second literal)
- [ ] A wallet session with `0 < energy < 0.5 kWh` produces zero debit and is marked COMPLETED
- [ ] No GST Invoice and no Settlement Entry created for a sub-0.5 kWh wallet session
- [ ] A wallet session at exactly 0.5 kWh and above debits for its **total** energy (cliff boundary, strict `<`)
- [ ] Tests cover the boundary (0.49 / 0.50 / 0) and assert no-debit/no-invoice for the waived band

## Blocked by

- `.scratch/de-minimis-refund/issues/01-qr-de-minimis-waiver.md` (defines the shared `MIN_BILLABLE_ENERGY_KWH` constant)

## Comments

- **2026-06-20 — Implemented.** Wallet billing widened to the same cliff (no debit), consuming the shared constant. Tests added (de-minimis ×2 + cliff) — green.
