# Funding source flag and live QR budget tiles on charger detail

Status: ready-for-agent

## What to build

Two related capabilities on the admin charger detail page (`/admin/chargers/{id}`):

1. **Funding-source visibility.** An admin viewing a charger with an active transaction cannot tell from the UI whether the session is wallet-funded or QR-funded. Surface this.
2. **Live QR budget.** For QR sessions, the customer has prepaid a fixed amount; the system already tracks `budget_limit_paise` in Redis (`qr_session:{transaction_id}`) and computes `remaining = budget_limit − cost` inside `check_budget_and_auto_stop` for the auto-stop dispatch. Expose that same `{budget_limit, cost_so_far, remaining}` triple to admins live.

### Backend

- Add `funding_source: "WALLET" | "QR" | "NONE"` to the `/api/admin/transactions/{transaction_id}` response. Derivation: `"QR"` if a `QRPayment` row references the transaction, `"WALLET"` if the transaction owner is a non-internal-role user with a Wallet, `"NONE"` otherwise (internal-role test sessions).
- Extract a pure helper `compute_budget_snapshot(transaction_id) -> {budget_limit, cost_so_far, remaining} | None` from the existing `QRPaymentService.check_budget_and_auto_stop` (the math at `qr_payment_service.py:577–589`). Returns `None` for non-QR sessions. Inherits the existing Redis cache-miss → DB rebuild fallback unchanged.
- Refactor `check_budget_and_auto_stop` to call the helper for its math. The auto-stop side-effect (writing `latest_reading_kwh` / `latest_power_kw` / `latest_meter_at` into the cache, and dispatching `RemoteStopTransaction` when `cost >= budget_limit`) stays in the original function — the helper is **pure**. This refactor must be behavior-preserving.
- When `funding_source == "QR"`, include a nested `qr_session` block in the transaction response with `budget_limit`, `cost_so_far`, `remaining` as Decimal-as-string ₹ values. Omit the block otherwise.

### Frontend

Augment the existing Current Charging Session card (`frontend/app/admin/chargers/[id]/page.tsx:743–792`):

- Render a `[QR]` badge next to the transaction ID whenever `funding_source === "QR"`.
- When `funding_source === "QR"`, render a 3-tile row below the existing fields: `Budget ₹X.XX  Spent ₹Y.YY  Remaining ₹Z.ZZ`, plus a progress bar (`cost_so_far / budget_limit` clamped to `[0, 1]`, with overflow flagged in a visually distinct way for the negative-remaining case).
- When `funding_source !== "QR"`, the badge and budget row do not render.

Layout reference:

```
Current Charging Session
Txn 509  [QR]   Status RUNNING   Started 06:18:27
                          Energy Consumed 1.24 kWh
─────────────────────────────────────────────────
Budget ₹490.00   Spent ₹12.34   Remaining ₹477.66
████░░░░░░░░░░░░░░░░ 2.5%
```

## Acceptance criteria

- [ ] Backend response includes `funding_source` for all transactions.
- [ ] `funding_source == "QR"` iff a `QRPayment` row references the transaction.
- [ ] Backend response includes `qr_session: {budget_limit, cost_so_far, remaining}` (Decimal strings) when and only when `funding_source == "QR"`.
- [ ] `compute_budget_snapshot` exists as a standalone, pure (no Redis writes, no RemoteStop dispatch) helper and is unit-tested.
- [ ] `check_budget_and_auto_stop` produces byte-identical auto-stop behavior to pre-refactor — regression-covered by its existing tests.
- [ ] Cache-miss path still rebuilds the qr_session row from DB when the helper is called against a transaction whose Redis key has expired.
- [ ] Frontend shows the `[QR]` badge only for QR-funded transactions.
- [ ] Frontend renders the 3-tile budget block and progress bar only for QR-funded transactions; wallet/internal-role sessions show neither.
- [ ] Negative `remaining` (the documented "auto-stop missed a frame" case) renders without crashing and is visually distinguishable from the normal case.
- [ ] `cd frontend && npm run build` passes.
- [ ] `docker exec ocpp-backend pytest` passes (baseline flakes excepted per `CLAUDE.md`).

## Blocked by

None — can start immediately.
