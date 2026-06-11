# Sentry triage — last 24h (2026-06-11)

Issues filed from Sentry root-cause analysis of all errors last seen within 24h.
Org `idofthings`, projects `ocpp-backend` + `ocpp-frontend`.
Query: `lastSeen:-24h`.

| # | Sentry | Title | Type | Status |
|---|---|---|---|---|
| 01 | OCPP-FRONTEND-5 | ThemeContext localStorage SecurityError (Safari) | AFK | ready-for-agent |
| 02 | OCPP-BACKEND-1Q | PostBootState None-response crash | AFK | ready-for-agent |
| 03 | OCPP-BACKEND-R | Downgrade cross-env QR webhook log noise | AFK | ready-for-agent |
| 04 | OCPP-BACKEND-A | Stop error-logging StopTransaction txn=-1 | AFK | ready-for-agent |
| 05 | OCPP-BACKEND-7 | Redis removal resilient to DNS loss on deploy | AFK | ready-for-agent |
| 06 | OCPP-BACKEND-9 | RemoteStartTransaction timeout → 504 | AFK | ready-for-agent |
| 07 | OCPP-BACKEND-3 | Dedup/cooldown stuck-payout detector alerts | AFK | ready-for-agent |
| 08 | OCPP-BACKEND-3 | Resolve stuck payouts for franchisee 2 (ops) | HITL | ready-for-human |
| 09 | OCPP-BACKEND-P/N | Investigate Clerk webhook signature failures | HITL | ready-for-human |
| 10 | (cross-cutting) | Tag backend Sentry events with real release, not `dev` | AFK | ready-for-agent |

## Implementation status (2026-06-11)

Issues 01–07 + 10 (all `ready-for-agent`) **implemented on branch `ops/log-rotation-and-tail-default`**, with tests:

- **01** ThemeContext `readStoredTheme`/`writeStoredTheme` try/catch guards. Frontend `npm run build` ✅.
- **02** PostBootState `None`-response guard. Test: `test_post_boot_state.py::test_none_response`.
- **03** QR cross-env miss `error`→`info`. Test extends `test_qr_cross_env_qr_code_not_found` (asserts no ERROR log).
- **04** StopTransaction unknown-txn `error`→`warning`. Test: `test_stop_transaction_handler.py`.
- **05** Redis removal catches `ConnectionError`/`TimeoutError`/`OSError`→`warning`. Tests in `test_infrastructure.py`.
- **06** RemoteStartTransaction timeout→504 + 504 excluded from Sentry `failed_request_status_codes`. Tests in `test_chargers.py`.
- **07** Per-franchisee dedup + cooldown (`STUCK_PAYOUT_ALERT_COOLDOWN_HOURS`, default 24h). Tests in `test_stuck_payout_detector.py`.
- **10** Sentry release = `SENTRY_RELEASE`/`GIT_COMMIT`/`env-timestamp`; `GIT_COMMIT` wired through 3 compose files + `make {staging,prod}-rebuild`; startup warns on fallback. Verified at runtime.

**08 + 09 investigated 2026-06-11** (prod read-only via SSM, user-authorized):
- **08** — **RESOLVED / self-healed.** Franchisee 2's only 2 ledger entries (id 15, 24) are now `TRANSFER_PROCESSED` with Razorpay transfer IDs; account `ACTIVE`. Were transiently stuck in `TRANSFER_INITIATED` awaiting the Razorpay transfer webhook. No money stuck, no action. Detector spam prevented by issue 07's dedup.
- **09** — **benign cross-environment Clerk traffic, not a bad secret.** Proven: 4 driver (`USER`) accounts with `clerk_user_id` were created via the webhook *during* the failure window (05-30 → 06-08), so the prod secret is correct and sign-ups sync fine. The 3 failing messages are signed by the shared Clerk app's other endpoint. **Code fix applied**: verification failure → `warning` + `200`, bypassing the generic error handler (which stays `error`). Test added. One optional human step: remove the duplicate Clerk webhook endpoint in the dashboard.

## Triage notes

- **Genuine code bugs**: 01, 02
- **Genuine ops/data issue**: 08 (franchisee 2 unsettled payouts) + 07 (alert hygiene)
- **Error-level log noise → downgrade**: 03, 04, 05
- **Needs investigation before fix**: 09 (stale secret vs probes), 06 (env timeout altitude)
