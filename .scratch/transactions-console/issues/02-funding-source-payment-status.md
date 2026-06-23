# Transactions Console — funding source + native payment status axis

Status: ready-for-agent
Type: AFK

## What to build

Add the second status axis to the **Transactions Console**: per-session **Funding Source** and **Payment Status**, as columns and filters. This is what turns the page from a session list into an operational triage console (find stuck refunds, billing failures, pending payments from one screen).

Two truthful, native status axes — deliberately NOT collapsed into one derived status (the canonical cross-funding "PaymentStatus" projection was considered and rejected as lossy; see `CONTEXT.md` → **Transactions Console**):

- **Session Status** — native `TransactionStatusEnum` (already shown from slice 01).
- **Payment Status** — the **actual, verbatim native** status of the session's backing payment record: the real `QRPaymentStatusEnum` value (PAID…REFUNDED, REFUND_FAILED, EXPIRED) for a **QR Session**, the real wallet-transaction status for a **Wallet Session**, none for an **Internal-role Session**. Never projected into a synthesised enum.
- **Funding Source** — `QR` / `Wallet` / `Internal`, derived via the existing `_resolve_funding` helper. A **multi-select** filter/column that disambiguates which native vocabulary a row's Payment Status belongs to.

Extend the existing `GET /transactions` endpoint in place (do NOT stand up a parallel endpoint that would drift). Enrich each page of sessions WITHOUT N+1: batch-load backing records with a single `QRPayment.filter(transaction_id__in=[...])` and a single `WalletTransaction.filter(...)` keyed by the page's transaction IDs, then stitch in memory; derive funding source over the batch. Add the new `funding_source` (multi-select) and `payment_status` query filters. Surface both as columns + filters on the page. Ship backend tests for the enrichment + filters, and run the frontend production build.

## Acceptance criteria

- [ ] `GET /transactions` returns per-row funding source + native payment status, batched (no per-row queries)
- [ ] New `funding_source` (multi-select) and `payment_status` filters supported by the endpoint
- [ ] Console shows Funding Source + Payment Status columns; Payment Status is the verbatim native value (no derived/synthesised enum)
- [ ] Filtering "QR + REFUND_FAILED" returns only stuck QR refunds; Internal sessions show no payment status
- [ ] Backend tests cover enrichment correctness and the new filters; N+1 avoided
- [ ] `cd frontend && npm run build` passes

## Blocked by

- `.scratch/transactions-console/issues/01-console-page-mvp.md`

## Comments

- **2026-06-20 — Implemented.** GET /transactions enriched (batched, no N+1) with funding_source + verbatim native payment_status; multi-select funding_source + payment_status filters added. Console columns/filters built. Wallet payment-status resolved to blank (no native enum — design refinement, see CONTEXT.md). 15 backend tests green; FE build green.
