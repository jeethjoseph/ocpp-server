# QR de-minimis energy waiver (< 0.5 kWh → full refund, no bill)

Status: ready-for-agent
Type: AFK

## What to build

Extend the **Zero-energy Session** full-refund path on the **QR Session** side to cover the new **De-minimis Session** band: a session that delivered `0 < energy_consumed_kwh < 0.5 kWh` is now treated like a zero-energy session — the customer is refunded `amount_paid` in full (instant `speed=optimum` via the existing `_full_refund` path), **no GST Invoice and no Settlement Entry are created**.

This is a *cliff*, not an allowance: a session at or above 0.5 kWh continues to bill for its **total** energy from the first Wh — the half-unit is never carved off the top. The single `energy < 0.5` check **subsumes** the existing `≤ 0` check (and negative meter-rollback readings), so it replaces the zero-energy branch rather than adding a second one.

The legal basis is a **de-minimis goodwill waiver of a real (tiny) supply** — deliberately NOT ADR 0002's "no taxable supply occurred." Reflect that honesty in the audit/refund reason string: keep `"Zero energy delivered"` only when `energy ≤ 0`; otherwise emit a band-accurate reason naming the de-minimis energy and the 0.5 kWh threshold.

Introduce the threshold as a single hardcoded policy constant `MIN_BILLABLE_ENERGY_KWH = Decimal("0.5")` (one source of truth, importable by the wallet path in the follow-up slice). Not an env var — changing the policy goes through code review + an ADR amendment.

See ADR 0013 (`docs/adr/0013-de-minimis-energy-waiver.md`) and the **Non-billable Session** / **Minimum billable energy** glossary entries in `CONTEXT.md`. Per project testing convention, ship tests and a QR simulator scenario alongside.

## Acceptance criteria

- [ ] `MIN_BILLABLE_ENERGY_KWH = Decimal("0.5")` defined once as a shared, importable constant
- [ ] QR settlement routes `0 < energy < 0.5 kWh` to a full refund of `amount_paid` (instant speed), the same path as zero-energy
- [ ] No GST Invoice and no Settlement Entry (`CommissionLedgerEntry`) created for a sub-0.5 kWh QR session
- [ ] A session at exactly 0.5 kWh and above bills for its **total** energy (cliff boundary, strict `<`)
- [ ] Refund/audit reason string is band-accurate: `"Zero energy delivered"` for `energy ≤ 0`, a de-minimis-specific reason naming the kWh and threshold otherwise
- [ ] Tests cover the boundary (0.49 / 0.50 / 0 / negative) and assert no-invoice/no-settlement for the waived band
- [ ] QR simulator scenario delivering a sub-0.5 kWh session demonstrates the full refund

## Blocked by

None - can start immediately

## Comments

- **2026-06-20 — Implemented.** QR settlement widened to the 0.5 kWh cliff; shared MIN_BILLABLE_ENERGY_KWH constant; band-accurate reason. Tests added (de-minimis/cliff/band-accuracy) — full QR+wallet+e2e suites green (112 passed).
