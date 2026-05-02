# Known Issues

Issues observed in production/staging that we've decided NOT to fix
immediately. Each entry: when discovered, the symptom, the root cause,
the impact, and the deferred fix.

---

## 1. Razorpay UPI fees recorded from webhook differ from settled fees

**Discovered:** 2026-05-02, while debugging txn 90 settlement.

**Symptom:** `qr_payment.platform_fee` carries the webhook-delivered fee,
which can disagree with what Razorpay actually charges. Concrete case:

| Source | Payment `pay_SkLcgPsBFwsvCq` (₹10 UPI) |
|---|---|
| `qr_code.credited` webhook payload | `fee: 12 paise`, `tax: 2 paise` (₹0.12 total) |
| Razorpay dashboard (post-settlement) | Total Fee: ₹0.00 |
| Our DB (`qr_payment id=3`) | `platform_fee=0.12`, `fee_source=webhook` |

**Root cause:** Razorpay's `qr_code.credited` / `payment.captured`
webhooks carry the merchant's *plan-rate* fee, which is then zeroed
out post-hoc to comply with NPCI's zero-MDR rule on UPI P2M
transactions ≤ ₹2000 (RBI directive, Apr 2020). No subsequent webhook
notifies us about the adjustment; the dashboard just silently reflects
the settled-state ₹0.

**Impact** (small per transaction, accumulates):

1. **Customers under-refunded** when `energy_cost + gst < amount_paid`.
   For txn 89 (energy=0): we refunded ₹9.88 instead of the full ₹10.00.
   The phantom ₹0.12 stayed in our nodal balance.
2. **Franchisees under-paid** in settlement. For txn 90 the ledger
   computed `franchisee_payout=₹5.83` using `pg_fee=₹0.12`. With actual
   `pg_fee=₹0`, the payout would have been ₹5.91 — a ₹0.08 shortfall.
3. **Platform accidentally retains the difference** — neither Razorpay
   (no fee actually charged), nor franchisee (paid less), nor customer
   (refunded less) gets that money. It sits in the nodal balance
   unattributed.

**Why deferred:** Per-transaction amounts are small (paise to a few
rupees on ₹10–₹200 sessions). Customer-facing visibility is low
(refund delta is on the order of ₹0.10). Settlement delta to
franchisee is similarly small. We accept this drift while the QR /
Route flow is in pilot.

**Fix when revisited:** Change priority order in
`services.qr_payment_service._resolve_platform_fee` to
**API → webhook → 2% estimate** (currently webhook → API → 2%).
`razorpay_service.fetch_payment_fees(payment_id)` already exists and
returns the post-settlement actual fee. Trade-off: extra ~200 ms
Razorpay round-trip at refund-decide / settlement-compute time. The
flows already do Razorpay round-trips at those points (refund call,
transfer call), so the additional latency is in the noise.

**Backfill** when fixing: scan `qr_payment` rows where
`fee_source IN ('webhook', 'estimated') AND status IN ('COMPLETED', 'REFUNDED')`,
re-fetch real fee, recompute correct refund, issue corrective
top-up refunds for any deltas above MINIMUM_REFUND_AMOUNT. Same for
under-paid franchisee settlements (issue a follow-up Route transfer
for the shortfall, capped at remaining transferable balance per
Razorpay's `sum(transfers) ≤ captured_amount` rule).

**Owner / next review:** Revisit when (a) the QR flow exits pilot, or
(b) cumulative drift exceeds ₹500 across the ledger (whichever comes
first). Track via the admin reconciliation report.
