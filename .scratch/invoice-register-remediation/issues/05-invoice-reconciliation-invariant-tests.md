# Property-based invariant tests for GST Invoice reconciliation

Status: done

## What to build

Lock the reconciliation identities of the **GST Invoice** behind property-based tests, so the rounding class of defect cannot return silently.

Before ADR 0026 the invoice reconstructed its total from independently-rounded components — energy and gateway taxable values were each quantised to paise, then the sum was grossed back up by the GST multiplier. Two upward half-paise compounded, and invoice totals exceeded cash actually collected by **₹9.61 across 65 of 226 pre-change production invoices**. The current code anchors the total to stored values instead and the variance is now exactly ₹0.00 across every post-change invoice — but nothing asserts it. The old code passed its tests too, because the tests used fixed amounts and nobody had asserted that the invoice total equals the cash received.

Three identities must hold exactly, for every invoice:

```
energy_taxable_value + gateway_charges  ==  total_taxable_value
total_taxable_value + total_tax + round_off  ==  total_amount
total_amount  ==  amount_paid - refund_amount          (QR Sessions only)
```

Generate random `(amount_paid, refund, kWh, rate_gst_included, gst_percent)` across realistic ranges — including the adversarial cases that produced the original defect: near-zero kWh, refunds within a rupee of the full payment, amounts whose GST-exclusive value lands exactly on a half-paisa boundary, and zero-gateway wallet sessions.

**Do not assert a fourth identity of the form `total_amount == kWh × rate_gst_included`.** That product is not representable in paise for most kWh values, and `energy_consumed_kwh` is itself back-derived from an already-rounded taxable value using a 4-decimal rate. Chasing it would require breaking one of the three identities above. The residual is disclosed on the face of the invoice as the Round Off line per ADR 0017, which is the correct treatment; the remaining ~1.3 paise per invoice is the representation floor, not a defect.

Fold in the numbering invariants from issues 01 and 02 so one suite covers the whole register: every generated invoice number is ≤ 16 characters, matches the expected format, and is unique within `(franchisee, series, financial_year)`.

## Acceptance criteria

- [ ] Property-based test asserts all three reconciliation identities hold exactly across randomised inputs
- [ ] Adversarial cases explicitly covered: near-zero kWh, near-full refund, half-paisa boundary values, zero-gateway wallet sessions
- [ ] A regression test reproduces the historical double-rounding case (₹50.00 paid → invoice must total ₹50.00, not ₹50.01) and fails against the pre-ADR-0026 arithmetic
- [ ] Numbering invariants asserted: length ≤ 16, format match, uniqueness within `(franchisee, series, financial_year)`
- [ ] No test asserts `total_amount == kWh × rate_gst_included`; a comment records why
- [ ] Suite runs in the existing pytest setup with no new service dependency
- [ ] Affected per-file pytest green (`docker exec ocpp-backend pytest`)

## Blocked by

- `.scratch/invoice-register-remediation/issues/02-sixteen-character-invoice-number-series.md` (for the numbering invariants; the reconciliation identities can be written immediately)
