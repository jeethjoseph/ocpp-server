# Refund-speed → churn cohort analysis

**Status:** parked — instrumentation defined, waiting for the cohort to mature.
**Revisit:** ~2026-09 (≈60–90 days from 2026-06-23), or once each arm has enough matured customers (see *Decision gate*).
**Related:** [ADR 0002](../../docs/adr/0002-zero-energy-full-refund.md) · New Relic dashboard *"VoltLync — QR Refunds & Charging"* · `QRRefundFinalSpeed` event.

## The question

Do **slow** refunds lose customers? When a QR (appless) charging session fails or
delivers zero energy, we issue a full refund and request **instant** speed
(`speed=optimum`). Razorpay downgrades many of these to **normal** (5–7 day) speed
per the customer's destination bank — *not* our balance (proven in ADR 0002). Does
that slow refund measurably reduce the chance the customer charges with us again?

## Why this is a (defensible) natural experiment

Every customer in the cohort had the **same** bad experience — a refundable failed
session — and we requested instant for all of them. Razorpay's per-bank IMPS rail
then decided quasi-randomly whether each refund cleared **fast (`instant`)** or
**slow (`normal`)**. So comparing the two arms isolates refund *speed* while holding
the failure experience constant. The difference in return rates is the churn
plausibly **attributable to slowness**; absolute non-returns in the slow arm are
"lost," but only the *delta vs the fast arm* is caused by speed.

## Definitions (frozen — do not drift)

| Concept | Definition |
|---|---|
| **Population** | Production only. Staging = test/simulator traffic, excluded. |
| **Customer key** | `COALESCE(customer_vpa, customer_contact)` — VPA, falling back to phone so a UPI-handle change doesn't read as a new person. |
| **Cohort entry** | A customer's **first** full refund (`refund_amount >= amount_paid`) with a known final speed. First, not last → avoids immortal-time bias. |
| **Entry time** | `COALESCE(refund_processed_at, updated_at)`. |
| **Arm** | Final `razorpay_refund_speed_processed`: `instant` = **fast** (control), `normal` = **slow** (treatment). This is the webhook-updated *final* value, not the optimistic creation-time value. |
| **Return event** | Any later paid session (`razorpay_payment_id IS NOT NULL`, `created_at > entry_time`) by the same customer key. |
| **Windows** | `returned_30d`, `returned_60d`; `duration_days` for survival. |
| **Maturity / censoring** | Score a customer on the 30d (60d) window **only** if entry was ≥30d (≥60d) ago. Everyone younger is right-censored — *never* counted as "lost." |

**Confounders to stratify/adjust for** (captured at entry, available on the row):
refund ₹ amount, station/charger, destination bank (VPA suffix, e.g. `@okhdfcbank`),
first-ever vs already-repeat customer.

## The queries — `cohort.sql`

| # | Purpose |
|---|---|
| Q1 | Data span & coverage (sanity). |
| Q2 | Repeat-customer baseline (context — are QR users one-and-done?). |
| **Q3** | **Primary** cohort summary: fast vs slow, 30d & 60d return rates, matured denominators. |
| Q4 | Survival export — one row per customer (`arm`, `event_returned`, `duration_days`) for Kaplan-Meier / Cox. |
| Q5 | (Optional) accumulation-snapshot table + insert for weekly tracking. |

Run against **prod** via the in-VPC postgres container (RDS is not publicly
reachable). The header of `cohort.sql` has the copy-paste SSM recipe.

## Readout method (at maturity)

1. **Kaplan-Meier** survival curves (event = charged again; time = days since refund),
   one per arm, **log-rank** test for separation. KM is required *because* of censoring.
2. **Cox proportional-hazards** adjusting for the confounders above — so a difference
   isn't actually "slow refunds happened more at a flaky station."
3. **Exec view:** Q3's 2×2 return rates on matured customers, with confidence intervals.

## Decision gate (write it down so nobody reads tea leaves at week 3)

Interpret the arm difference **only** when **each arm has ≥30 matured customers**
AND median follow-up ≥30d. Originally targeted ≥50/arm, but the **fast (`instant`)
arm is the binding constraint** — instant only happens on full refunds and only
~30–40% clear instant, so at 2026-06 volume (~4–5 instant/month) ≥50 fast is ~10
months out. Options when revisiting:
- **(a)** Lower the bar to ≥30/arm → clean causal read at ~5–6 months, wider CIs.
- **(b)** Add a **propensity-matched no-refund control** (≈77 customers who never
  needed a refund) for a directional read at ~2 months — bigger N, but confounded by
  the fact that refunded customers had a failed session.
- **(c)** Re-estimate as charger count / usage scales (timelines shrink with volume).

## Snapshot as of 2026-06-23 (why it's parked)

Production, first-refund basis: **6 fast / 19 slow** customers with a recorded-speed
refund; only **~10** have had 14 days to return. Return rates were statistically
indistinguishable (matured slow ≈50%, vs a **52%** overall repeat baseline) on
single-digit counts — **no signal yet, and far too small to decide anything.**
`speed_processed` only exists since migration 40 (2026-05-20), so there is ~1 month
of speed-tagged history. **Do not make a gateway/spend decision on this data.**

## When you return to this

1. Re-run `cohort.sql` Q1–Q3 against prod; check arm sizes vs the decision gate.
2. If the gate is met, export Q4 and run KM + log-rank + Cox.
3. If still short on the fast arm, switch to option (b) above for a directional read.
4. The likely *fix* if churn is real is a proactive comms nudge ("refund on its way,
   your bank usually credits in 5–7 days") — cheaper than a gateway change and
   A/B-testable on the slow arm.
