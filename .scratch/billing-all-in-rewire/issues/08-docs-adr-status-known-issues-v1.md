# Docs: ADR status lines, known-issues narrowing, v1 context docs

Status: ready-for-agent

## What to build

Bring the documentation in line with the shipped behavior (ADR 0026). ADR 0026, `CONTEXT.md`, and the plan are already written; this slice updates the surrounding docs: add `Status:` / superseded-by lines to ADR 0001 and ADR 0003 marking their gateway-fee portions superseded by 0026; narrow `docs/known-issues.md#1` to reflect that the webhook fee is now the operative gateway (customer over-refund residual on zero-MDR persists, franchisee untouched); and update the two v1 context documents (`docs/v1/llm-context-document.md`, `docs/v1/comprehensive-architecture-documentation.md`) to describe tariff = base+GST, gateway = actual separate line, and the retired synthetic fee. Do this last so the docs reflect what actually shipped.

## Acceptance criteria

- [ ] ADR 0001 + ADR 0003 carry a status/superseded-by pointer to ADR 0026 for the gateway-fee decisions
- [ ] `docs/known-issues.md#1` updated to the narrowed form (actual gateway operative; residual accepted; franchisee unaffected)
- [ ] `docs/v1/llm-context-document.md` + `docs/v1/comprehensive-architecture-documentation.md` reflect the new tariff/gateway model and the column rename
- [ ] No remaining doc references present the synthetic 2% fee or "all-in tariff" as current behavior

## Blocked by

- 03-qr-billing-energy-from-base-rate-actual-gateway.md
- 04-qr-invoice-settlement-actual-gateway.md
- 05-wallet-path-cleanup.md
