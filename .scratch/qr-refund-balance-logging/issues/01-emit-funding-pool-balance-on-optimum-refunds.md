# Emit funding-pool balance on optimum-refund diagnostics

Status: ready-for-agent

## What to build

When a QR full refund is issued at instant speed (`speed=optimum`), capture the Razorpay funding pools — the **Account balance (Razorpay float)** and the **Refund Credits** wallet — at the moment of the refund, and attach them to the existing `QRRefundSpeed` New Relic event and the refund success log line. This is a diagnostic to confirm or kill the working hypothesis that `optimum → normal` downgrades are caused by a thin settlement float (see ADR 0002, 2026-06-18 amendment).

End-to-end behaviour: an `optimum` refund reads the funding pools just **before** the refund POST, then emits a `QRRefundSpeed` event carrying `balance_before` and `refund_credits_before` (in rupees) alongside the existing `speed_processed`. An analyst can then query, in New Relic, whether `speed_processed = normal` correlates with a `balance_before` below the refund amount.

Scope and contract (locked during grill-with-docs):
- **Only `speed == "optimum"` refunds** are instrumented. Partial / normal-speed refunds are untouched (their funding pool is irrelevant — they never request instant).
- **Read before the POST**, not after — a post-refund balance has already been debited and can't show whether the float was sufficient.
- **Best-effort, strictly additive**: a new `RazorpayService.fetch_balance()` helper with a 5s timeout that swallows all errors to `None`. A failed/slow balance read must never delay, retry-storm, or fail the refund. The `QRRefundSpeed` event still fires with `balance_before = null` on failure.
- **Fields are raw rupees** (`/v1/balance` returns paise — `42268` → `₹422.68`). Capture `balance` and `refund_credits` separately (do not pre-sum — once Refund Credits is enabled we want to see which pool funded it). Ignore the response's `updated_at` / `last_fetched_at` fields — they are unmaintained, but the `balance` / `refund_credits` values are real-time.
- **No DB column, no migration.** The data lives only in the NR event and the log line.

Touch points: `services/razorpay_service.py` (new `fetch_balance()`), `services/monitoring_service.py` (`record_refund_speed` gains `balance_before` / `refund_credits_before`, added to the event payload), `services/qr_payment_service.py` (`_full_refund` reads the balance before the optimum POST and threads it into `record_refund_speed` + the log line). Keep functions under 40 lines.

## Acceptance criteria

- [ ] `RazorpayService.fetch_balance()` returns the primary account `balance` and `refund_credits` converted paise→rupees; returns `None` on timeout / 5xx / parse error without raising (5s timeout).
- [ ] On a `speed=optimum` full refund, the balance is fetched **before** the refund POST and the `QRRefundSpeed` NR event carries `balance_before` and `refund_credits_before` in rupees.
- [ ] When `fetch_balance()` returns `None` or raises, the refund still completes and the `QRRefundSpeed` event still fires with `balance_before = null` (best-effort regression guard).
- [ ] Partial / normal-speed refunds are unchanged — no balance fetch, no new fields.
- [ ] The refund success log line includes `balance_before` and `refund_credits_before`.
- [ ] Unit tests cover: `fetch_balance` happy path (paise→rupees) and failure path; `_full_refund` best-effort guard; `record_refund_speed` emits the two new fields; existing `record_refund_speed` mocks updated for the new signature. Run `docker exec ocpp-backend pytest tests/test_qr_payment_service.py`.
- [ ] `docs/v1/llm-context-document.md` and `docs/v1/comprehensive-architecture-documentation.md` updated to reflect the new diagnostic. (CONTEXT.md terms and the ADR 0002 amendment are already written.)

## Blocked by

None - can start immediately

## Comments

**2026-06-18 — Implemented** on branch `feat/qr-refund-balance-logging`. `RazorpayService.fetch_balance()` (5s, errors→None), `_fetch_funding_pools()` wrapper (never raises), `_full_refund` snapshots before the optimum POST and threads `balance_before`/`refund_credits_before` into `record_refund_speed` + the log line, `QRRefundSpeed` event enriched. Tests: `tests/test_razorpay_balance.py` (fetch_balance happy/missing/HTTP-error/network-error/not-configured + record_refund_speed fields) and `tests/test_qr_payment_service.py` (best-effort guard + updated optimum mocks). Full backend suite: 545 passed, 0 failed. Docs: CONTEXT.md terms, ADR 0002 amendment, llm-context + comprehensive-architecture all updated. Not yet committed.
