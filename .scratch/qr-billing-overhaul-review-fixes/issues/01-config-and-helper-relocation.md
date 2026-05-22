# Config & synthetic-fee helper relocation

Status: ready-for-agent

## What to build

Two interleaved problems from the qr-billing-overhaul senior review:

- `RAZORPAY_PLATFORM_FEE_PERCENT` currently lives in `services/qr_payment_service.py`, but it's read by `main.py` (startup validation), `routers/chargers.py` (back-derivation on POST + PATCH), `services/invoice_service.py` (indirectly via the synthetic helpers), and `services/qr_payment_service.py` itself. Three of those four use function-level imports to dodge circular-import risk. The variable is project-level config, not a QR-payment domain concept.
- `_synthetic_platform_fee` and `_synthetic_fee_split` are imported from `services/qr_payment_service.py` into `services/invoice_service.py` despite their underscore prefix (Python convention for "module-internal"). The next engineer who sees `_` will assume they're free to refactor, breaking invoice generation.

This issue fixes both together because they're the same kind of problem (the wrong module owns shared state) and the fix touches the same set of files.

### Plan

- Create `backend/core/config.py` and move `RAZORPAY_PLATFORM_FEE_PERCENT = Decimal(os.getenv(...))` there. `QR_PAYMENT_PENDING_TIMEOUT` (currently next to it in `qr_payment_service.py`) is QR-specific — leave it where it is.
- Move `_synthetic_platform_fee` and `_synthetic_fee_split` into `services/tariff_utils.py` (which already owns `back_derive_rate_per_kwh`) and **drop the underscore prefix** → public `synthetic_platform_fee`, `synthetic_fee_split`. The module's docstring should call out that this is the single home for all "synthetic gateway fee" math, mirroring how `back_derive_rate_per_kwh` is already there.
- `_ensure_actual_fee_captured` stays in `qr_payment_service.py` — it's the only function that talks to the Razorpay SDK and reads/writes the `QRPayment` row, both of which are QR-domain. Leave the underscore prefix (it really is module-internal now).
- Update every caller: `qr_payment_service.py`, `invoice_service.py`, `routers/chargers.py`, `backend/main.py`, and tests (`test_qr_payment_service.py`).
- Remove the function-level `from services.qr_payment_service import RAZORPAY_PLATFORM_FEE_PERCENT` imports inside `chargers.py:create_charger` and `chargers.py:update_charger` — they exist solely to dodge circular imports that disappear after this refactor.

See [ADR 0001](../../../docs/adr/0001-synthetic-vs-actual-platform-fee.md) and [ADR 0003](../../../docs/adr/0003-all-inclusive-tariff-with-operator-absorption.md) for the policy context.

## Acceptance criteria

- [ ] `backend/core/config.py` exists and exports `RAZORPAY_PLATFORM_FEE_PERCENT`. `qr_payment_service.py` re-exports it for backwards compatibility OR all readers are updated (pick one — document the call in the PR).
- [ ] `services/tariff_utils.py` exports public `synthetic_platform_fee(amount_paid)` and `synthetic_fee_split(amount_paid)`. No leading underscore.
- [ ] No file outside `services/qr_payment_service.py` imports a `_`-prefixed name from it (grep confirms).
- [ ] `routers/chargers.py` has zero function-level imports for the moved symbols.
- [ ] Backend test suite passes (321 tests, no regressions).
- [ ] `docs/v1/llm-context-document.md` and `docs/v1/comprehensive-architecture-documentation.md` updated to reflect the new module locations.

## Blocked by

None — can start immediately.
