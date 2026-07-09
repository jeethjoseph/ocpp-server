# 06 — Payment-provider abstraction (design + build) [CONTINGENT PLACEHOLDER]

Status: ready-for-human

## What to build

**Contingent placeholder — do not start until the Go/No-Go decision (05) says "proceed."** The abstraction's shape depends on gate findings (which Paytm products passed, where they diverge from Razorpay), so detailed acceptance criteria are deliberately deferred to avoid writing fiction now.

Intended scope, to be re-sliced after 05:
- Introduce a provider-agnostic seam so Paytm can be added alongside Razorpay. The current seam candidate is `razorpay_service.py` (~150 refs), but Razorpay is also woven through `franchisee_onboarding_service`, `franchisee_settlement_service`, `qr_payment_service`, the webhooks router, `wallet_payments`, and provider-specific model columns (`razorpay_*`).
- Open design questions for the re-slice: one `PaymentProvider` interface vs separate interfaces per concern (collection / refunds / settlement / onboarding); how to handle provider-specific identifiers on models; how webhook signature verification and event normalization are abstracted.

## Acceptance criteria

- [ ] (To be defined after the Go/No-Go decision — this issue must be re-sliced into concrete tracer bullets before work begins)

## Blocked by

- 05 — Go/No-Go decision + ADR
