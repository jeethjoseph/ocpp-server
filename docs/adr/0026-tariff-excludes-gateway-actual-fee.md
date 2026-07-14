# Tariff excludes the gateway fee; the gateway is the actual webhook fee, billed as a separate line

**Status:** accepted — supersedes the gateway-fee portions of [ADR 0001](0001-synthetic-vs-actual-platform-fee.md) and [ADR 0003](0003-all-inclusive-tariff-with-operator-absorption.md).

## Context

Under ADR 0001/0003 the operator-typed tariff was an **all-in** number that baked GST *and* a fixed **synthetic 2% gateway fee** into one per-kWh figure (`tariff_per_kwh_all_in`), and `rate_per_kwh` was back-derived as `all_in × (1 − fee%/100) / (1 + gst%/100)`. Because the synthetic gateway was a fixed rupee amount on the *full* `amount_paid`, a partially-consumed QR session refunded less than the pure energy owed — the customer's effective ₹/kWh exceeded the advertised tariff by ~2% of their refund. Measured exposure across staging+prod on 2026-07-13: 988 billed sessions, 394 overcharged, ₹346 total, tail-heavy (only 4 sessions ≥ ₹10). ADR 0003 had recorded this distortion as an intentional consequence; we are now reversing that call.

## Decision

1. **The Tariff excludes the gateway.** The operator types a **GST-inclusive, gateway-exclusive** energy price (`Tariff.rate_gst_included`, renamed from `tariff_per_kwh_all_in`). It is the source of truth for the customer-facing displayed tariff. The **Base rate** (`rate_per_kwh`, retained) is back-calculated as `rate_gst_included / (1 + gst%/100)` and drives line-item billing (`energy_cost = kWh × base_rate`).
2. **The gateway fee is the actual Razorpay charge**, as reported by the `qr_code.credited` webhook, sized on the full `amount_paid`, billed as a **separate customer-facing line** on the GST Invoice — never folded into the Tariff. The **synthetic 2% fee is retired**; `RAZORPAY_PLATFORM_FEE_PERCENT` and its helpers (`synthetic_platform_fee`, `synthetic_fee_split`, `back_derive_rate_per_kwh`) are removed.
3. **The gateway is a pass-through.** It is added to what the customer pays, and subtracted in *both* the refund (`refund = amount_paid − energy_incl_gst − gateway`) and the settlement ledger (`pg_fee_amount = actual gateway`). It therefore **cancels out of the franchisee's payout** — the franchisee's pool is `energy_kWh × base_rate`, independent of the gateway. This also reverses ADR 0001's 2026-05-29 synthetic-ledger amendment (safe precisely because the fee now cancels).
4. **Budget cap reserves the actual gateway.** `max_kwh = (amount_paid − actual_gateway) / (rate_per_kwh × (1 + gst%/100))`, computed at StartTransaction from the webhook fee already on the row.
5. **Wallet is unchanged** — base + GST, no gateway line (the top-up gateway fee is absorbed at top-up, not per session).

## Migration

Pure rename + one back-calc, no value transform on the displayed number and **no schema change beyond the rename**:
- `Tariff.tariff_per_kwh_all_in → rate_gst_included` (value unchanged); `rate_per_kwh = rate_gst_included / (1 + gst%/100)` recomputed in the same migration's `upgrade()`.
- `GSTInvoice.tariff_per_kwh_all_in → rate_gst_included` (snapshot column; historical rows keep their original gateway-inclusive value under the new name — invoices are immutable and the PDF re-renders each line from its own stored component fields, so the header number stays accurate per-row).

**One-time transition effect:** for existing tariffs, retaining the displayed number while pulling the gateway out as a separate line means the effective customer total ticks up ~2% (the old displayed number already contained a gateway; now the actual gateway adds on top). This is a deliberate, admin-adjustable relabel — "the base rate is now slightly higher" — not an ongoing double-count. At the current fleet size (~2 live chargers) ops adjusts by re-entering the tariff if desired.

## Consequences

- The energy line can never distort: it is computed directly as `kWh × base_rate`, not as a residual after subtracting a gateway. The ADR 0003 partial-consumption overcharge, the gateway-on-total clamp, and the ADR 0023 phantom-invoice class all disappear structurally.
- **Known-issue #1 (webhook vs settled fee)** persists in a narrowed form: for a zero-MDR payment where the webhook over-states the settled fee, the customer is over-refunded by the webhook amount and VoltLync absorbs the residual. The franchisee is untouched (fee cancels). We accept this — the webhook is the only per-payment fee signal available at billing time.
- **Historical remediation: fix-forward only.** The ₹346 pre-existing overcharge (de-minimis, 322 rows below Razorpay's ₹1 refund floor) is not retroactively refunded; this is a recorded materiality decision.
- `rate_per_kwh` is **retained** (not retired as an earlier draft proposed); its existing stored values are already valid base rates. The `tariff_drift_check` module and `RAZORPAY_PLATFORM_FEE_PERCENT` startup validation are removed (no synthetic identity left to police).
- **Single-payment assumption:** the energy-ceiling + per-payment refund math assumes one QR Payment per session (enforced today by reject-on-busy). ADR 0021 (stackable budget) is a decision doc that was never implemented; if built, budget/refund must aggregate at session level (sum of per-payment fees, LIFO refund split).

## Reviewed residuals (accepted, 2026-07-14)

A three-lens review (billing-math / concurrency / migration) verified the core is algebraically sound (gateway cancels out of the franchisee payout; `total_amount + refund == amount_paid` and `net_excl_gst == invoice energy_taxable` hold exactly; `refund ≥ 0` is structural). These residual tradeoffs were surfaced and are **consciously accepted**:

1. **Pricing predictability reversed.** The customer's *total* now varies with Razorpay's actual fee (ADR 0001's fixed-fee predictability goal is retired). Deliberate — the fee is the only per-payment signal we have, and some payments genuinely carry one.
2. **Zero-MDR under-refund residual.** When the `qr_code.credited` webhook over-states the settled fee (UPI P2M ≤ ₹2000 is zero-MDR), the customer is under-refunded by the webhook amount (paise–₹2) and VoltLync retains it. Franchisee untouched (fee cancels). See known-issues #1.
3. **Unobservable-fee margin window.** If the fee is unknown at StartTransaction (webhook lacks `fee` *and* the fees API is down) but recovers by billing, the reserved budget was `amount_paid` while billing caps energy at `amount_paid − fee` — VoltLync absorbs ≤ one gateway-fee of over-delivered energy. Never overcharges the customer; refund stays ≥ 0.
4. **Capped-session ledger vs invoice kWh.** In the rare over-consumption-capped case the settlement ledger stores full metered kWh (and a correspondingly understated `tariff_rate_per_kwh`) while the invoice stores billable kWh. Payout is driven by `net_excl_gst`, so money is unaffected; the two artefacts disagree only on the reported kWh/rate.
5. **Legacy-invoice note wording.** Old (pre-2026-07) invoices re-rendered today show the note "Tariff quoted (incl. GST)" instead of the original "(all-inclusive)". Values and reconciliation are unchanged (each PDF re-renders from its own stored component fields) — cosmetic only.
6. **Historical overcharge: fix-forward only.** The ₹346 pre-existing overcharge (322 rows below Razorpay's ₹1 refund floor) is not retroactively refunded — a recorded de-minimis materiality decision.
