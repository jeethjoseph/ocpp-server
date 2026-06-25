# A sub-0.5 kWh session is fully refunded and not billed — as a goodwill waiver, not a non-supply

> **Status: amended 2026-06-24 — the de-minimis *waiver* described below is REVERSED.** Completed sub-0.5 kWh sessions now bill; only a FAILED session that delivered a little is refunded. The original text is kept for history; read the Amendment first.

## Amendment (2026-06-24): completed sub-0.5 kWh bills; only FAILED-after-trivial-delivery refunds

The original decision — full-refund (QR) / no-debit (wallet) for **every** `0 < energy < 0.5 kWh` session, with no invoice or settlement — is **reversed**. New policy, keyed on `transaction_status` × energy:

| status \ energy | `≤ 0` | `0 < e < 0.5` | `≥ 0.5` |
|---|---|---|---|
| **COMPLETED** (clean StopTransaction) | full refund *(ADR 0002)* | **bill** | bill |
| **STOPPED** (timeout / disconnect / sweep / force-stop) | full refund *(ADR 0002)* | **bill** | bill |
| **FAILED** (abnormal — `_fail_transaction_with_billing`) | full refund | **full refund** (fault) | bill |

- The fault-refund is **keyed strictly on `transaction_status == FAILED`** (`wallet_service.py`, `qr_payment_service.py`). It is the *only* status that triggers the sub-0.5 kWh refund. **Code is the source of truth for this** — if the predicate and this table ever diverge, the code wins and this table must be corrected to match.
- A **STOPPED** session bills exactly like COMPLETED. `finalize_stopped_transaction` (the canonical path for `SUSPENDED_TIMEOUT`, `DISCONNECT_TIMEOUT`, `STALE_SUSPEND_SWEEP`, `STALE_RECONNECT`, and admin force-stop) always sets status **STOPPED**, never FAILED — so a session that delivered `0 < e < 0.5 kWh` and was cleaned up by a timeout/sweep/force-stop **bills for that energy**. Only the StatusNotification-driven `_fail_transaction_with_billing` path produces FAILED and thus the fault-refund. This is deliberate: a clean-but-trivial delivery is a real supply regardless of *how* the session ended; only an abnormal fault waives it.
- A **COMPLETED** session that delivered any energy is **billed from the first Wh** (`energy × rate + GST`, GST invoice, settlement entry; refund only the unused prepaid change). **No minimum-charge floor.**
- A **FAILED** session (charger stopped without a clean StopTransaction, or socket-grace timeout) that delivered `0 < energy < 0.5 kWh` is **fully refunded** (QR) / **not debited** (wallet) — the "intended a lot, faulted after delivering a little" case.
- A **FAILED** session that delivered `≥ 0.5 kWh` is **billed** — the customer got a real charge despite the fault.
- `energy ≤ 0` remains a full refund under **ADR 0002** (no taxable supply), regardless of status.

### Why the reversal
The waiver gave completed charges away for free and left the **franchisee unpaid for energy they actually delivered**. Two things outweigh the billing friction the original optimized for:
1. **The customer received the service.** Someone who pays for ~0.2 kWh and completes the session happily should not be refunded — they got what they paid for.
2. **The franchisee earns a legitimate settlement** for real energy delivered. The original "franchisee absorbs the de-minimis kWh" consequence is the specific grievance being corrected.

The friction the original cited (a GST invoice + settlement entry + change-refund gateway fee on a ~₹5 session, some settlements landing below the Razorpay payout threshold and accumulating) is **accepted as the price of correctness**, not disputed.

### `MIN_BILLABLE_ENERGY_KWH` is repurposed
`MIN_BILLABLE_ENERGY_KWH = Decimal("0.5")` no longer means "minimum energy to bill" (completed sessions bill from the first Wh). It is now the **fault-refund ceiling**: the maximum energy a **FAILED** session can have delivered and still be fully refunded. Symmetric across QR (full refund) and wallet (no debit).

### "De-minimis Session" retired
The glossary term **De-minimis Session** (a *waived* completed sub-0.5 session) no longer exists — those sessions bill. The only non-billable bands are now **Zero-energy** (ADR 0002) and **Fault-refund** (FAILED + sub-0.5, this amendment).

---

_Original decision (now superseded by the amendment above):_

A **Charging Session** that delivers `0 < energy_consumed_kwh < 0.5 kWh` (the **Minimum billable energy**, a half-unit) is treated as a **De-minimis Session**: the customer is refunded in full (QR) or not debited at all (wallet), **no GST invoice and no Settlement Entry are created**, and the franchisee silently absorbs the trivial delivered kWh. This widens the existing zero-energy full-refund path (ADR 0002) from `≤ 0` to `< 0.5`, but the justification is deliberately different and must not be conflated with ADR 0002's.

## Why this is *not* ADR 0002 reasoning

ADR 0002 skips the invoice because **no taxable supply occurred** — nothing was delivered. That is airtight for `energy ≤ 0` and **does not extend** here: at 0.4 kWh a real, taxable supply *did* happen. We are not claiming otherwise. We are **waiving** the charge for a genuine supply because the consideration is de minimis — at a ~₹25/kWh all-in tariff the most we ever forgo is ~₹12, and collecting it means issuing a GST invoice, creating a settlement entry, and (on QR) a partial refund that carries its own gateway fee. The friction and CX cost of billing a near-nothing session exceeds the revenue. So we give the trivial energy away as goodwill.

A future reader/auditor must see the honest basis: **waived supply (de minimis goodwill)**, not **non-supply**. The audit/refund reason string is band-accurate — `"Zero energy delivered"` only for `energy ≤ 0`, otherwise `"De-minimis energy {x} kWh < 0.5 kWh — waived"`.

## It is a cliff, not an allowance

The 0.5 kWh threshold is a discontinuity, not a free slab carved off every session:

| Delivered | Billed |
|---|---|
| 0.49 kWh | ₹0 — full refund / no debit, no invoice |
| 0.50 kWh | full 0.50 kWh × rate + GST, normal invoice + settlement |
| 2.00 kWh | full 2.00 kWh × rate + GST |

A session at or above 0.5 kWh bills for its **total** energy from the first Wh. An allowance model (first 0.5 kWh always free) was rejected — it would bleed revenue on *every* session and invite stop/restart gaming to stay under the bar repeatedly. A cliff only ever fires on genuinely trivial sessions.

## Scope and shape

- **Symmetric across funding sources.** Applies to both **QR Sessions** (full refund) and **Wallet Sessions** (no debit). The waiver is a property of the *supply*, not of how it was paid for; splitting them would mean a customer's bill depends on card-vs-QR for the same 0.3 kWh.
- **Threshold is a hardcoded `Decimal` constant** (`MIN_BILLABLE_ENERGY_KWH = Decimal("0.5")`), single source of truth imported by both the QR and wallet billing paths — not an env var. Changing the policy goes through code review + an ADR amendment, not a quiet per-environment deploy edit.
- **Keyed on energy, never power.** "500 W" (a rate) never enters the decision; only `energy_consumed_kwh` (the half-unit delivered) does.
- The single `energy < 0.5` check **subsumes** the old `≤ 0` check (and negative meter-rollback readings), so it replaces the zero-energy branch rather than adding a second one.

## Consequences

- **The franchisee absorbs the de minimis kWh.** A waived session delivered up to 0.5 kWh of the franchisee's grid electricity (~≤₹5 wholesale) with no Settlement Entry, so they earn nothing for it. Accepted as negligible at fleet scale; building a VoltLync-reimburses-franchisee path for ≤₹5 events is more machinery than the problem warrants. Revisit if waived-session volume ever becomes material.
- The CONTEXT.md relationship "a billable, non-internal session produces exactly one GST Invoice and one Settlement Entry" now turns on **billable** (energy ≥ 0.5 kWh), not "non-zero-energy."
- **Zero-energy Session** remains its own glossary term and keeps ADR 0002's non-supply justification; **De-minimis Session** is the new band. Both are **Non-billable Sessions**.

## Considered alternatives

- **Copy ADR 0002's "no taxable supply" rationale.** Rejected: factually wrong for a non-zero delivery; an auditor reading "no invoice for 0.4 kWh delivered" needs the goodwill-waiver basis, not a false non-supply claim.
- **Free allowance (first 0.5 kWh of every session free).** Rejected: bleeds revenue on every session and invites stop/restart gaming. Cliff chosen instead.
- **Env-var threshold.** Rejected for now: it's a policy tied to this ADR, not an operational dial that should vary between staging and prod. Promote to env var only if ops ever needs to tune it live.
- **QR-only (skip wallet).** Rejected: creates an unjustifiable asymmetry where the same 0.3 kWh is free on QR but billed on wallet.
- **Reimburse the franchisee for the waived energy.** Rejected at current scale: ≤₹5 per rare event doesn't justify keeping a settlement entry alive on a session we've told the customer is free.
