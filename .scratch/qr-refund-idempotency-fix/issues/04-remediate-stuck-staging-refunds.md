# Remediate the 5 stuck staging refunds (~₹253)

Status: done (resolved organically — verified, no action taken)

## What to build

Five staging QR payments are stuck in `REFUND_FAILED` with the HTTP 409 idempotency collision and were **never actually refunded** — verified 2026-06-09 that `GET /payments/{id}/refunds` returns `count=0` for all five at Razorpay. These are real customers on staging.voltlync.com owed real money on the shared live Razorpay account (~₹253 total).

| qr_payment id | razorpay_payment_id | refund owed |
|---|---|---|
| 227 | pay_Sypb5hhlx5WJmD | ₹9.78 |
| 230 | pay_SysbHaHwJLOiiV | ₹60.81 |
| 232 | pay_Sz1GdAnzuZpp6H | ₹29.68 |
| 235 | pay_SzBDfLEarerhc5 | ₹7.88 |
| 236 | pay_SzHFGx4kdK3pRW | ₹144.22 |

Re-issue the refund for each using the corrected globally-unique idempotency key (from slice 01) so it no longer collides with the prod-registered key. Then mark each row `REFUNDED` with its new `razorpay_refund_id`. This is HITL because it moves real money on the live account — a human must approve the run and verify the refunds in the Razorpay dashboard.

Rows #204 (₹0.02) and #46 (₹0.23) are correctly terminal (below Razorpay's ₹1.00 floor) — acknowledge, do not refund.

## Acceptance criteria

- [ ] Before re-issuing, re-confirm `count=0` at Razorpay for each of the 5 payments (no double-pay)
- [ ] Refund re-issued for #227, #230, #232, #235, #236 with the corrected unique key and the original refund amount
- [ ] Each row updated to `REFUNDED` with a populated `razorpay_refund_id`
- [ ] New refunds visible in the Razorpay dashboard for the 5 payment ids
- [ ] #204 and #46 left as terminal below-minimum (not refunded), retry noise stopped (depends on slice 03)
- [ ] Human approval obtained before executing the live refund run

## Blocked by

- 01-globally-unique-refund-idempotency-key

## Comments

**2026-06-09 — interaction with issue 01 (now implemented).** Slice 01 changed the refund idempotency key to the globally-unique `refund_{razorpay_payment_id}`. The 5 stuck rows have a stored `refund_amount` and a 409 `failure_reason` (not `below_razorpay_minimum`), so the moment slice 01 is **deployed to staging**, the 30-min `BillingRetryService` sweep will retry them with the new non-colliding key and auto-refund them (~₹253) on the next tick — without the HITL approval gate this issue assumes. Before deploying slice 01 to staging, decide: accept the automatic remediation (then this issue collapses to *verify the 5 went REFUNDED + dashboard check*), or temporarily gate the retry sweep and execute this issue manually under approval first.

**2026-06-09 — resolved organically before any manual run; verified, no money moved by us.**

A pre-flight re-scan (the prudent "any more cases?" check) found the 5 rows had ALREADY been refunded automatically at 07:36–07:37 UTC by the existing staging retry sweep — NOT by deploying slices 01–03 (still undeployed). Verified on both sides:

| qr id | status | razorpay_refund_id | amount | Razorpay |
|---|---|---|---|---|
| 227 | REFUNDED | rfnd_SzS5261yysmOuk | ₹9.78 | count=1, processed |
| 230 | REFUNDED | rfnd_SzS53nzckbgsBU | ₹60.81 | count=1, processed |
| 232 | REFUNDED | rfnd_SzS55Qwtkybc1y | ₹29.68 | count=1, processed |
| 235 | REFUNDED | rfnd_SzS57CcR7sFAGo | ₹7.88 | count=1, processed |
| 236 | REFUNDED | rfnd_SzS59B9sO9L1Tl | ₹144.22 | count=1, processed |

Likely cause: Razorpay idempotency keys expire ~24h after first use. Once prod's registration of the colliding `qr_payment_{id}` keys aged out, the staging retry's reuse stopped 409ing and the refund went through. The `/tmp/remediate_refunds.py` script was prepared and approved-pending but NOT run (its per-payment `count==0` pre-check would have skipped all 5 anyway). No double-refund risk materialised.

Remaining REFUND_FAILED rows are correct and need no refund: **#46** (₹0.23) and **#204** (₹0.02), both below Razorpay's ₹1 floor. #46 keeps drawing retry-noise on staging until slice 03 deploys (its legacy long-form reason dodges the current exact-match exclusion). Prod remains 0 REFUND_FAILED.
