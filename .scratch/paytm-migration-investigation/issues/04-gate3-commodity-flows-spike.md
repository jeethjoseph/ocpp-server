# 04 — Gate 3: Commodity flows spike (QR + webhooks + orders)

Status: ready-for-agent

## What to build

Prove the low-risk, commodity payment flows on Paytm in sandbox. Only worth building once Gate 1 (the driver) passes — these are table-stakes features almost any PSP has, so they gate nothing on their own.

- **Dynamic QR**: create and close a dynamic QR code for an order (Paytm Create QR Code API), analogous to our per-charger appless QR flow.
- **Webhooks**: receive Paytm's S2S webhook on a terminal transaction and verify its signature/checksum (note: Paytm webhooks require port 443).
- **Orders + checkout**: create an order and verify the payment signature/checksum, analogous to our wallet top-up flow.
- Map each to the corresponding Razorpay capability so the abstraction design (later) has a concrete correspondence table.
- Throwaway spike; sandbox only.

## Acceptance criteria

- [ ] Dynamic QR create + close demonstrated in sandbox
- [ ] Webhook received and signature/checksum verified
- [ ] Order created and payment signature/checksum verified
- [ ] A Razorpay↔Paytm capability correspondence table produced for QR/webhook/order
- [ ] Spike code isolated and disposable

## Blocked by

- 01 — Gate 1: Instant-refund reliability spike
