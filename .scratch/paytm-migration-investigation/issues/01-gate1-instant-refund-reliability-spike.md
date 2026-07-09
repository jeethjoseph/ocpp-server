# 01 — Gate 1: Instant-refund reliability spike (quantitative bar)

Status: ready-for-agent

## What to build

The kill-switch for the whole Paytm investigation. A throwaway spike that answers one question empirically: **are Paytm instant refunds materially more reliable than Razorpay's for our UPI-VPA refund pattern?** — the actual driver for this migration (Razorpay silently downgrades instant refunds to normal via opaque fraud-shield / per-VPA-24h rules; ref ticket #19564492).

Docs cannot answer this: Paytm's public docs are equally opaque on refund risk rules and, like Razorpay, only report refund speed **asynchronously** (webhook / status API), with no request-time downgrade signal. So this must be measured, not read.

- **Establish the Razorpay baseline**: measure our current real instant-refund (`speed=optimum`) success rate — how often refunds actually processed instant vs silently downgraded to normal — over a representative recent window.
- **Run the Paytm sandbox test**: fire a batch of instant refunds to UPI VPAs under **velocity / repeat-VPA / varied-amount** conditions (the conditions that trip Razorpay's shield). Record instant-success rate, silent-downgrade rate, and whether Paytm ever signals a downgrade earlier than Razorpay does.
- **Compare against a pre-agreed bar**: Paytm must beat the Razorpay baseline by a material margin to justify migrating. Merely matching Razorpay's silent-downgrade behavior = **FAIL → stop the initiative**.
- Throwaway spike (standalone scripts, Paytm sandbox creds). Not wired into `razorpay_service` or any abstraction. Delete after.

## Acceptance criteria

- [ ] Razorpay instant-refund actual success rate is measured and documented (the baseline)
- [ ] Paytm sandbox instant refunds tested under velocity/repeat-VPA/varied-amount conditions
- [ ] Instant-success rate, silent-downgrade rate, and downgrade-signal timing captured for Paytm
- [ ] A written pass/fail verdict against the quantitative bar (Paytm must materially beat the Razorpay baseline)
- [ ] Spike code is isolated and disposable — no changes to production payment code

## Blocked by

- None - can start immediately
