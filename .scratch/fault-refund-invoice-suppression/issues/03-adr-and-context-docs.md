# 03 — ADR + context-doc update for the net-retained issuance rule

Status: done

## Comments

- Done 2026-07-09. Added `docs/adr/0023-invoice-only-when-net-retained-positive.md`
  (net-retained issuance rule, the invoice-61 failure it fixes, cross-refs to ADR
  0002 / 0013 / 0001 / 0017, and the prepaid invariant). Updated the invoicing
  sections of `docs/v1/llm-context-document.md` and
  `docs/v1/comprehensive-architecture-documentation.md` to state the net-retained
  guard.


## What to build

Record the invoice-issuance rule established in issue 01 as a durable decision so
the next person touching billing doesn't re-introduce the metered-energy guard.

- **ADR** capturing: "A GST tax invoice is issued only when the customer's net
  amount retained is positive (`amount_paid - refund_amount > 0` for QR;
  `total_billed > 0` for wallet)." Explain why the earlier `energy_consumed_kwh > 0`
  guard was wrong (fully-refunded fault sessions — ADR 0013 band — still had
  metered energy > 0 but zero billed amount, producing invoice 61 and violating
  the prepaid invariant `total_amount + refund_amount == amount_paid`). Reference
  ADR 0013 (fault-refund band) and ADR 0001 (synthetic gateway fee). Add as a new
  ADR under `docs/adr/`, numbered after the current highest.
- **`docs/v1/llm-context-document.md`** and
  **`docs/v1/comprehensive-architecture-documentation.md`** — update the QR
  billing / invoicing sections to state the net-retained issuance rule, per the
  CLAUDE.md "update these documents when done" convention.

## Acceptance criteria

- [ ] A new ADR records the net-retained issuance rule, the invoice-61 failure it fixes, and links to ADR 0013 + ADR 0001
- [ ] `llm-context-document.md` reflects the net-retained issuance rule in the invoicing section
- [ ] `comprehensive-architecture-documentation.md` reflects the same
- [ ] The ADR states the prepaid invariant (`total_amount + refund_amount == amount_paid`) as the invariant issuance must preserve

## Blocked by

- 01 — Suppress GST invoice issuance when net amount retained is zero
