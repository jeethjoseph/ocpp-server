# 05 — Go/No-Go decision + ADR

Status: ready-for-human

## What to build

Synthesize the three gate results into a migration decision, and record it. This is the pivot between "investigation" and "commitment."

- Consume Gate 1 (refund reliability verdict — the driver), Gate 2a+2b (split-settlement viability), and Gate 3 (commodity flows).
- Decide one of: **full replacement**, **dual-rail** (e.g. Paytm for collection/refunds, Razorpay retained for settlement, or vice-versa), or **abort** (stay on Razorpay; pursue the shield-rule escalation / Refund Credits cushion / a different PSP instead).
- Weight the decision on Gate 1 above all: if Paytm did not materially beat the Razorpay instant-refund baseline, the migration's only driver is unmet and the default is abort.
- **If proceeding**, write the migration ADR: the decision, the driver, the gate evidence, the rejected alternatives (stay-and-escalate, dual-rail if not chosen), and the consequences (franchisee re-onboarding, RBI re-validation, TDS handling).

## Acceptance criteria

- [ ] All gate verdicts summarized in one place
- [ ] A decision recorded: full-replace / dual-rail / abort, with the rationale weighted on Gate 1
- [ ] If proceeding: an ADR authored in `docs/adr/` capturing decision, evidence, alternatives, consequences
- [ ] If aborting: the reason and the alternative path (escalate/Refund Credits/other PSP) documented
- [ ] Contingent slices (06 abstraction, 07 cutover) are re-scoped or closed based on the decision

## Blocked by

- 01 — Gate 1: Instant-refund reliability spike
- 03 — Gate 2b: Paytm Split Settlement technical spike
- 04 — Gate 3: Commodity flows spike
