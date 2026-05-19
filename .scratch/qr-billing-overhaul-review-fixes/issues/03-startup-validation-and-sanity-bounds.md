# Startup validation tests + sanity bounds for RAZORPAY_PLATFORM_FEE_PERCENT

Status: ready-for-agent

## What to build

Two related gaps from the senior review:

- **M3 — no test for the existing `≤ 0` startup validation.** `backend/main.py:1644-1650` raises `RuntimeError` if `RAZORPAY_PLATFORM_FEE_PERCENT <= 0`, but nothing tests it. A future contributor who "made it optional" would break launch with no regression signal.
- **L2 — no upper-bound sanity check.** A fat-finger `RAZORPAY_PLATFORM_FEE_PERCENT=20` (intended `2.0`) would silently 10× the deduction on every QR payment and every customer-facing display. Need a defensive ceiling.

### Plan

- Add a defensive upper-bound check in `main.py` startup:
  - `> 10` → `RuntimeError` (off-by-decimal-point — refuse to start; this is almost certainly a misconfiguration)
  - `> 5` → `logger.error` warning (legitimately high but flagged for ops review)
  - `0 < x <= 5` → normal startup (the existing info-level log line)
  - `<= 0` → `RuntimeError` (existing behaviour)
- Add `pytest` cases that monkeypatch the constant and assert the right behaviour for each band. Note: the check runs in the FastAPI startup event, so tests will need to invoke the startup event handler directly (or extract the validation into a testable helper and call that — the helper-extraction route is cleaner).
- Optionally extract the validation into `backend/core/config.py:validate_platform_fee_percent()` if Slice 1 has landed by the time this is implemented — that's a nicer testing surface than poking the FastAPI startup event.

The 5 / 10 thresholds are best-guesses based on real-world payment-gateway fee ranges; Razorpay is typically 0–2% for UPI and up to 3% for cards. 5% is "weird but possible," 10% is "definitely wrong."

## Acceptance criteria

- [ ] `RAZORPAY_PLATFORM_FEE_PERCENT=20 docker compose up backend` exits with a clear `RuntimeError` mentioning the value and the expected range.
- [ ] `RAZORPAY_PLATFORM_FEE_PERCENT=6 docker compose up backend` starts but emits an `ERROR`-level log line.
- [ ] `RAZORPAY_PLATFORM_FEE_PERCENT=2.5 docker compose up backend` starts normally.
- [ ] `RAZORPAY_PLATFORM_FEE_PERCENT=-1` and `RAZORPAY_PLATFORM_FEE_PERCENT=0` both refuse to start.
- [ ] Unit tests cover all four bands.
- [ ] If Slice 1 has landed, validation lives in `backend/core/config.py` as a testable helper; otherwise inline in `main.py` startup.

## Blocked by

None — can start immediately. Cleanest implementation depends on Slice 1 (so the validation can live next to the constant), but the work can proceed in either order.
