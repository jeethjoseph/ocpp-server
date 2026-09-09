# Issue-tracker reconciliation report

Generated against 125 issues currently marked `ready-for-agent` / `ready-for-human` across 36 features.

## How to read this — and what it does NOT do

This report **does not decide whether an issue is done.** It was built to, and
that turned out to be unsound: issues cite existing files and symbols as *context*,
so a naive 'do the things it mentions exist?' check scores almost everything as
complete. A hand-verified control case (`ws-disconnect-tracking/04`, confirmed NOT
done) still scored 0.94 under that approach.

What survived is narrower and more trustworthy: claims are read **only from
prescriptive sections** (`What to build`, `Acceptance criteria`, `The fix`, …), and
the useful output is the **misses** — artifacts those sections name that do not
exist anywhere in the repo. A miss is strong evidence work remains. A clean score
is weak evidence of anything.

| Bucket | Meaning | Action |
|---|---|---|
| **A — likely done** | every named artifact exists *and* the referenced code moved after filing | spot-check, then flip to `done` |
| **B — likely NOT done** | acceptance criteria names something absent from the repo | leave open; the miss says what's left |
| **C — needs human eyes** | too few machine-checkable claims to judge | read it |

**A: 4  ·  B: 32  ·  C: 89**

## Accuracy — checked against hand-verified cases

Spot-checked before publishing. Confirmed **true** positives:

- `release-pipeline/02,04` name `make staging-release` — **0 occurrences** in the Makefile.
- `ws-disconnect-tracking/04` names `CLOSE_GRACE_SECONDS` — absent; I also read
  `force_disconnect` and there is no `asyncio.wait_for` bound on the close.
- `qr-billing-overhaul/04` names `min_price_per_kwh_all_in` — absent from the repo.
- `charger-connectivity-zulip-alerts` — **the most valuable catch.** Commit `664574a`
  is titled *"zulip alerts"*, which reads as shipped. It contains **only the PRD and
  three issue files — zero code.** `ZulipAlertService`, `ZULIP_BOT_API_KEY` and
  `ZULIP_SITE` exist nowhere. Zulip alerting is planned, not built.

Known **false**-positive patterns — skip these when reviewing bucket B:

- **Renamed during implementation.** `rds-staging-migration/02,03` flag
  `POSTGRES_HOST` / `POSTGRES_SSL_MODE`, but the work shipped as `DB_HOST` /
  `DB_SSL_MODE` (`backend/db_ssl.py` exists). Done — just not under the proposed name.
- **Opaque identifiers quoted as examples.** Razorpay QR ids (`qr_StVw78FvfWrofx`) in
  `qr-regeneration-fix/02` and an OCPP message id (`boot_55C1E96E`) in
  `logs-console-correlated-reply/01` are illustrations, not artifacts to build.
- **Paths outside the repo.** `prod-deploy-2026-05/03` names a backup file under
  `/home/ec2-user/...` on the prod box, which will never be in git.
- **Test-function names**, which legitimately differ from what a spec proposed.

Rough precision on bucket B is ~70%. Good enough to triage; not good enough to
close or reopen anything unread.

---

---

## B — likely NOT done (has concrete misses)

The `missing` column is the point: each is an artifact the issue's own
acceptance criteria names, which is absent from the codebase.

### `active-session-on-my-charges`  <sub>filed 2026-05-22</sub>

| # | title | missing |
|---|---|---|
| 01 | Backend `qr-active-sessions` endpoint | `STALE_PAYMENT_THRESHOLD_SECONDS` |
| 06 | API contract cleanup: drop `budget_remaining`, expose stale threshold, s | `routers/_shared.py` |
| 09 | `/my-charges` component split + unified QRPayment active-state classifie | `_classify_sub_state` |

### `admin-reports`  <sub>filed 2026-07-09</sub>

| # | title | missing |
|---|---|---|
| 02 | 02 — Temperature aggregation endpoint (hourly/daily min-avg-max buckets) | `bucket_start`, `sample_count` |
| 04 | 04 — Temperature report CSV export | `bucket_start_ist` |

### `billing-all-in-rewire`  <sub>filed 2026-07-14</sub>

| # | title | missing |
|---|---|---|
| 02 | Retire the synthetic platform-fee scaffolding | `services/tariff_drift_check.py`, `test_tariff_drift_check.py` |

### `charger-connectivity-zulip-alerts`  <sub>filed 2026-07-14</sub>

| # | title | missing |
|---|---|---|
| 01 | Slice 1 — End-to-end charger-disconnect → Zulip (the spine) | `ZULIP_ALERTS_ENABLED`, `ZULIP_BOT_API_KEY`, `ZULIP_BOT_EMAIL`, `ZULIP_SITE` |
| 02 | Slice 2 — Add charger connect + rejection events | `ZulipAlertService` |
| 03 | Slice 3 — Provision Zulip bot & enable alerts per environment | `ZULIP_BOT_API_KEY`, `ZULIP_BOT_EMAIL`, `ZULIP_SITE`, `ZULIP_ALERTS_ENABLED` |

### `diagnostic-bundle-headerless`  <sub>filed 2026-08-27</sub>

| # | title | missing |
|---|---|---|
| 01 | Trim the Diagnostic Bundle upload response to a minimal ack | `_BODY_PREVIEW_CHARS`, `archive_only_lines`, `indexed_lines` |
| 05 | Stop parsing the bundle header and drop the seven header-derived columns | `BUNDLE_MAGIC`, `_HEADER_INT_FIELDS`, `_UINT32`, `_parse_bundle_header` |

### `franchisee-activation-reconciliation`  <sub>filed 2026-06-18</sub>

| # | title | missing |
|---|---|---|
| 01 | Periodic reconciliation poll for stuck KYC_SUBMITTED franchisees | `FRANCHISEE_ACTIVATION_POLL_INTERVAL_SECONDS`, `FranchiseeActivationReconciliationService`, `FRANCHISEE_ACTIVATION_POLL_INTERVAL_SECONDS` |

### `logs-console-correlated-reply`  <sub>filed 2026-07-09</sub>

| # | title | missing |
|---|---|---|
| 01 | Expand-to-reply: correlated OCPP response in the Logs Console | `boot_55C1E96E` |

### `ocpi-google-feed`  <sub>filed 2026-07-09</sub>

| # | title | missing |
|---|---|---|
| 02 | Feed scaffolding: Versions + Credentials + token auth + `OCPI_ENABLED` e | `OCPI_COUNTRY_CODE`, `status_message`, `OCPI_COUNTRY_CODE` |
| 03 | Locations module: static Location/EVSE/Connector + real-time status fusi | `OCCUPIED` |

### `paytm-migration-investigation`  <sub>filed 2026-07-09</sub>

| # | title | missing |
|---|---|---|
| 06 | 06 — Payment-provider abstraction (design + build) [CONTINGENT PLACEHOLD | `PaymentProvider` |

### `prod-deploy-2026-05`  <sub>filed 2026-06-18</sub>

| # | title | missing |
|---|---|---|
| 03 | Pre-deploy `pg_dump` of prod Docker postgres | `/home/ec2-user/ocpp-server/backups/prod_pre_deploy_2026-05-27.sql` |

### `qr-billing-overhaul`  <sub>filed 2026-05-22</sub>

| # | title | missing |
|---|---|---|
| 04 | Tariff API back-calc, field rename, and validation | `min_price_per_kwh_all_in` |

### `qr-billing-overhaul-review-fixes`  <sub>filed 2026-05-22</sub>

| # | title | missing |
|---|---|---|
| 01 | Config & synthetic-fee helper relocation | `_synthetic_fee_split` |
| 02 | Migration 36 safety hardening + smoke-test rework | `MIGRATION_36_BACKFILL_SQL`, `test_backfill_all_in_is_not_null_after_migration`, `MIGRATION_36_BACKFILL_SQL` |
| 04 | Doc + label hygiene + GST test coverage + seed_data correctness | `BACKFILL_FIXTURES`, `BACKFILL_FIXTURES` |
| 06 | Frontend test harness bootstrap (Vitest + React Testing Library) | `test_back_derive_30_at_18_pct_gst_and_2_pct_fee` |

### `qr-instant-refund`  <sub>filed 2026-05-22</sub>

| # | title | missing |
|---|---|---|
| 01 | Enable Razorpay instant refunds for all QR full-refund flows | `_wait_for_plug_in_then_start`, `process_payment_captured` |
| 02 | Augment _full_refund trigger tests with speed=optimum assertion | `_wait_for_plug_in_then_start`, `process_payment_captured` |

### `qr-refund-balance-logging`  <sub>filed 2026-07-14</sub>

| # | title | missing |
|---|---|---|
| 01 | Emit funding-pool balance on optimum-refund diagnostics | `record_refund_speed` |

### `qr-regeneration-fix`  <sub>filed 2026-06-18</sub>

| # | title | missing |
|---|---|---|
| 02 | Close the Razorpay QR on DB-insert failure in `_create_qr_for_charger` | `qr_StVw78FvfWrofx`, `qr_StVw9hlw7WgWZJ`, `qr_StVwIbN2nJ6a3Y`, `qr_StVwKqSAIQCNvK` |

### `rds-staging-migration`  <sub>filed 2026-06-18</sub>

| # | title | missing |
|---|---|---|
| 02 | Backend: bake RDS CA bundle into image, add SSL-aware DSN construction | `POSTGRES_HOST`, `POSTGRES_SSL_MODE`, `POSTGRES_HOST`, `POSTGRES_SSL_MODE` |
| 03 | Compose + .env.staging.example + Makefile changes for RDS readiness | `POSTGRES_HOST`, `POSTGRES_SSL_MODE`, `POSTGRES_HOST`, `POSTGRES_SSL_MODE` |

### `release-pipeline`  <sub>filed 2026-07-09</sub>

| # | title | missing |
|---|---|---|
| 02 | Tracer bullet: backend built in CI → ECR → staging release | `staging-release` |
| 04 | nginx in CI + full staging cutover | `staging-release` |
| 06 | Prod cutover: `deploy`-branch build, prod override, `make prod-release`, | `prod-release` |

### `ws-disconnect-tracking`  <sub>filed 2026-06-18</sub>

| # | title | missing |
|---|---|---|
| 04 | Bound the graceful-close wait in `force_disconnect` so a dead cellular s | `CLOSE_GRACE_SECONDS` |

---

## A — likely done (verify, then close)

### `active-session-on-my-charges`  <sub>filed 2026-05-22</sub>

| # | title | claims | commits since filed |
|---|---|---|---|
| 05 | Tariff cache: Decimal preservation + cache-miss drift warning | 9 | 8 |

### `charger-ws-auth`  <sub>filed 2026-07-09</sub>

| # | title | claims | commits since filed |
|---|---|---|---|
| 04 | 04 — Global REQUIRE_CHARGER_AUTH flag closes the window | 7 | 18 |

### `ocpi-google-feed`  <sub>filed 2026-07-09</sub>

| # | title | claims | commits since filed |
|---|---|---|---|
| 05 | Admin frontend: publish toggle UI + structured connector enum fields | 11 | 4 |

### `qr-instant-refund`  <sub>filed 2026-05-22</sub>

| # | title | claims | commits since filed |
|---|---|---|---|
| 04 | Emit metric counters for instant-refund succeeded vs fallback | 6 | 2 |

---

## C — needs human eyes

### `active-session-on-my-charges`  <sub>filed 2026-05-22</sub>

| # | title | claims | commits since filed |
|---|---|---|---|
| 02 | Frontend active-session card on `/my-charges` | 1 | 0 |
| 03 | Persist VPA in localStorage on `/my-charges` | 3 | 0 |
| 08 | Frontend resilience: loading/error UI, adaptive polling, shared clock, t | 2 | 0 |

### `admin-reports`  <sub>filed 2026-07-09</sub>

| # | title | claims | commits since filed |
|---|---|---|---|
| 01 | 01 — ADR: Reports framework + time-bucketing aggregation pattern | 4 | 0 |

### `availability-toggle-fix`  <sub>filed 2026-06-18</sub>

| # | title | claims | commits since filed |
|---|---|---|---|
| 01 | Add `availability` column to `Charger` model + Aerich migration | 4 | 0 |
| 03 | Frontend: switch availability toggle to read `Charger.availability` | 1 | 3 |
| 04 | ADR 0008 + doc updates: availability is separate from latest_status | 2 | 0 |

### `availability-toggle-fixes`  <sub>filed 2026-05-22</sub>

| # | title | claims | commits since filed |
|---|---|---|---|
| 01 | Frontend availability-toggle: honour OCPP response status, drop Faulted- | 4 | 0 |
| 04 | Pre-deploy blockers: revert M4 audit "fix" + replace generic Pydantic 42 | 3 | 0 |
| 05 | Polish: dead `note` field, cast chains, DRY, defensive data.success chec | 2 | 4 |

### `bill-card-consistency`  <sub>filed 2026-07-09</sub>

| # | title | claims | commits since filed |
|---|---|---|---|
| 01 | 01 — Accurate energy on the bill + make the receipt card match the bill | 3 | 0 |

### `billing-all-in-rewire`  <sub>filed 2026-07-14</sub>

| # | title | claims | commits since filed |
|---|---|---|---|
| 03 | QR billing → energy-from-base-rate + actual gateway, budget reserves act | 12 | 0 |
| 04 | QR invoice + settlement → actual gateway line | 11 | 0 |
| 05 | Wallet path cleanup — base + GST, no gateway line | 8 | 0 |
| 07 | Admin tariff form → GST-included input, base + GST preview | 6 | 0 |

### `charger-display-identity`  <sub>filed uncommitted</sub>

| # | title | claims | commits since filed |
|---|---|---|---|
| 02 | Sequence allocation and backfill ordering | 0 | 0 |
| 03 | Name hygiene and the display fallback contract | 0 | 0 |
| 04 | UPI payee/description composition with the code | 0 | 0 |
| 05 | Research: GST invoice equipment-identity requirements | 0 | 0 |
| 06 | Support lookup of the display code | 0 | 0 |

### `charger-search-debounce`  <sub>filed 2026-06-30</sub>

| # | title | claims | commits since filed |
|---|---|---|---|
| 01 | Debounce admin charger-list search & hold the list during refetch | 1 | 0 |

### `charger-ws-auth`  <sub>filed 2026-07-09</sub>

| # | title | claims | commits since filed |
|---|---|---|---|
| 01 | 01 — Basic Auth check on the WS handshake (schema + pre-accept enforceme | 4 | 0 |
| 02 | 02 — Per-charger enforcement + legacy-mode burn-down logging | 3 | 0 |
| 03 | 03 — Admin provisioning + rotation endpoint (reveal-once) | 2 | 0 |
| 05 | 05 — Follow-up: nginx edge rate-limiting on /ocpp/ (NAT-aware) | 3 | 0 |

### `de-minimis-refund`  <sub>filed 2026-06-30</sub>

| # | title | claims | commits since filed |
|---|---|---|---|
| 02 | Wallet de-minimis energy waiver (< 0.5 kWh → no debit, no bill) | 3 | 0 |

### `diagnostic-bundle-headerless`  <sub>filed 2026-08-27</sub>

| # | title | claims | commits since filed |
|---|---|---|---|
| 02 | Extract the in-band marker parser out of the fan-out into a shared modul | 9 | 0 |
| 03 | Bundle identity becomes SHA-256 of the body, replacing (epoch, bundle_se | 5 | 0 |
| 04 | Loss accounting becomes a UTC window derived from in-band TIME_SYNC anch | 13 | 0 |
| 06 | Make the S3 archive and the index row succeed or fail together | 3 | 0 |
| 08 | Revise the firmware spec to v2 and update the domain docs | 7 | 0 |
| 09 | Drop the superseded header columns after a soak period | 8 | 0 |

### `event-loop-hardening`  <sub>filed 2026-06-18</sub>

| # | title | claims | commits since filed |
|---|---|---|---|
| 09 | Fix ConnectionManager.force_disconnect lock concurrency bug | 2 | 0 |

### `firmware-update-hardening`  <sub>filed 2026-06-18</sub>

| # | title | claims | commits since filed |
|---|---|---|---|
| 01 | Firmware upload: fall back to local disk when AWS_S3_FIRMWARE_BUCKET is  | 7 | 0 |

### `franchisee-dashboard-improvements`  <sub>filed 2026-07-09</sub>

| # | title | claims | commits since filed |
|---|---|---|---|
| 01 | 01 — Franchisee analytics endpoint (payout/energy/sessions buckets + per | 10 | 0 |
| 02 | 02 — Franchisee dashboard graphs (reports 1–4) | 0 | 0 |
| 03 | 03 — Remove Gross from the franchise portal | 8 | 0 |
| 04 | 04 — /my-charges header + Dashboard link + sign-in resolver redirect | 0 | 0 |

### `internal-role-wallet-skip`  <sub>filed 2026-05-22</sub>

| # | title | claims | commits since filed |
|---|---|---|---|
| 02 | Internal-role sessions: skip wallet billing + budget cap, audit + metric | 4 | 0 |
| 03 | Webhook user-creation role gate + delete legacy internal-role wallets | 0 | 0 |
| 04 | Fix `Decimal is not JSON serializable` in redis_manager zero-energy stat | 3 | 0 |

### `invoice-register-remediation`  <sub>filed uncommitted</sub>

| # | title | claims | commits since filed |
|---|---|---|---|
| 01 | Franchisee invoice code with partitioned allocation (foundation) | 13 | 0 |
| 02 | New 16-character GST Invoice number series | 4 | 0 |
| 03 | Correct the supplier GSTIN on all GST Invoices | 5 | 0 |
| 04 | Fail loudly on missing or mismatched supplier identity | 9 | 0 |
| 05 | Property-based invariant tests for GST Invoice reconciliation | 3 | 0 |

### `ocpi-google-feed`  <sub>filed 2026-07-09</sub>

| # | title | claims | commits since filed |
|---|---|---|---|
| 01 | OCPI identity + connector schema (Aerich migration + backfill) | 29 | 0 |
| 04 | Admin backend: `publish_to_google` toggle (completeness gate + audit log | 12 | 0 |

### `paytm-migration-investigation`  <sub>filed 2026-07-09</sub>

| # | title | claims | commits since filed |
|---|---|---|---|
| 01 | 01 — Gate 1: Instant-refund reliability spike (quantitative bar) | 1 | 0 |
| 02 | 02 — Gate 2a: Paytm split-settlement commercial + compliance confirmatio | 2 | 0 |
| 03 | 03 — Gate 2b: Paytm Split Settlement technical spike | 4 | 0 |
| 04 | 04 — Gate 3: Commodity flows spike (QR + webhooks + orders) | 0 | 0 |
| 05 | 05 — Go/No-Go decision + ADR | 0 | 0 |
| 07 | 07 — Cutover plan [CONTINGENT PLACEHOLDER] | 0 | 0 |

### `prod-deploy-2026-05`  <sub>filed 2026-06-18</sub>

| # | title | claims | commits since filed |
|---|---|---|---|
| 01 | Create prod S3 buckets for invoices + firmware | 4 | 0 |
| 02 | Procure + populate new env vars in `.env.prod` on prod EC2 | 0 | 0 |
| 04 | Merge `develop → deploy` and run `make prod-deploy` | 1 | 0 |
| 05 | Post-deploy verification — confirm migrations + backend health on prod | 0 | 0 |
| 06 | Run `backfill_gst_schema.py` on prod | 1 | 0 |
| 07 | Run `backfill_below_threshold.py` on prod | 6 | 0 |
| 08 | Run `reconcile_wallet_balance.py` as validation (read-only) | 1 | 0 |
| 09 | Post-deploy smoke tests + 24-48h observation | 0 | 0 |

### `qr-instant-refund`  <sub>filed 2026-05-22</sub>

| # | title | claims | commits since filed |
|---|---|---|---|
| 03 | Persist Razorpay refund speed_processed and surface in admin UI | 4 | 0 |

### `qr-regeneration-fix`  <sub>filed 2026-06-18</sub>

| # | title | claims | commits since filed |
|---|---|---|---|
| 01 | Drop the stale UNIQUE constraint on `charger_qr_code.charger_id` | 3 | 0 |

### `rds-staging-migration`  <sub>filed 2026-06-18</sub>

| # | title | claims | commits since filed |
|---|---|---|---|
| 01 | Provision RDS Postgres staging instance + supporting network resources | 1 | 0 |
| 04 | Create app user + database on RDS, then dry-run dump + restore | 2 | 0 |
| 05 | Cutover runbook: switch backend from Docker postgres to RDS | 0 | 0 |
| 06 | Update docs + auto-memories to reflect the staging-RDS reality | 0 | 0 |

### `release-pipeline`  <sub>filed 2026-07-09</sub>

| # | title | claims | commits since filed |
|---|---|---|---|
| 01 | AWS foundation: ECR repos + OIDC trust + scoped push role | 0 | 0 |
| 03 | Frontend in CI: build args, secrets, Dockerfile ARG wiring | 6 | 0 |
| 05 | Migration step in the release flow + expand/contract checklist | 2 | 0 |

### `sentry-triage-2026-06-11`  <sub>filed 2026-06-18</sub>

| # | title | claims | commits since filed |
|---|---|---|---|
| 01 | Guard localStorage access in ThemeContext against Safari SecurityError | 2 | 0 |
| 02 | Null-check PostBootState response before reading .status | 2 | 0 |
| 03 | Downgrade cross-env QR webhook "no active ChargerQRCode" from error to i | 2 | 0 |
| 04 | Stop error-logging benign StopTransaction txn=-1 | 3 | 0 |
| 05 | Make Redis charger-removal resilient to DNS/connection loss on deploy | 2 | 0 |
| 06 | Return 504 + suppress Sentry error on RemoteStartTransaction timeout | 1 | 0 |
| 07 | Dedup/cooldown stuck-payout detector alerts | 1 | 0 |

### `socket-charger-classification`  <sub>filed 2026-07-09</sub>

| # | title | claims | commits since filed |
|---|---|---|---|
| 01 | 01 — Fix socket-charger classification + make connector_type admin-edita | 8 | 0 |

### `stackable-qr-payments`  <sub>filed 2026-07-09</sub>

| # | title | claims | commits since filed |
|---|---|---|---|
| 01 | 01 — Same-payer top-up replaces reject-when-busy (summed budget) | 8 | 0 |
| 02 | 02 — Rebuild-must-sum durability fix | 4 | 0 |
| 03 | 03 — LIFO refund of unused budget at StopTransaction | 1 | 0 |
| 04 | 04 — Customer-facing "pay again to charge longer" hint | 0 | 0 |

### `transactions-console`  <sub>filed 2026-06-30</sub>

| # | title | claims | commits since filed |
|---|---|---|---|
| 03 | Transactions Console — drill-down to session detail with payment + settl | 2 | 0 |

### `upsert-race-hardening`  <sub>filed 2026-07-09</sub>

| # | title | claims | commits since filed |
|---|---|---|---|
| 01 | 01 — Tariff: enforce one-tariff-per-charger (dedup + UNIQUE(charger_id)  | 6 | 0 |
| 02 | 02 — Drop the auto-created placeholder VehicleProfile in StartTransactio | 4 | 0 |

### `wallet-charging-gate`  <sub>filed 2026-06-18</sub>

| # | title | claims | commits since filed |
|---|---|---|---|
| 03 | 03 — Set flag on staging/prod + verify | 0 | 0 |
| 04 | 04 — Exempt internal-role (admin/franchisee) sessions from the wallet ga | 12 | 0 |

### `ws-disconnect-tracking`  <sub>filed 2026-06-18</sub>

| # | title | claims | commits since filed |
|---|---|---|---|
| 03 | New Relic dashboard + server_error alert + notification destination | 1 | 0 |

---

---

# Bucket B — hand-verified dispositions (2026-09-01)

All 32 were checked against the repo. **The audit's core assumption inverts for
removal issues**: when an issue exists to *delete* something, the absence of the
named artifact is proof of success, not of neglect. That alone moved one issue.

## Reclassified to `done` (4)

| Issue | Why the audit was wrong |
|---|---|
| `diagnostic-bundle-headerless/05` | **Removal issue.** Absence of `BUNDLE_MAGIC` / `_UINT32` / `_HEADER_INT_FIELDS` *is* the success condition. Shipped in `e9e65a3` under ADR 0030. |
| `rds-staging-migration/02` | Renamed in implementation: shipped as `DB_HOST` / `DB_SSL_MODE`, not `POSTGRES_*`. `backend/db_ssl.py` exists. |
| `rds-staging-migration/03` | Same rename; `DB_SSL_MODE` wired through all three compose files, `make staging-rds-shell` exists. |
| `qr-billing-overhaul/04` | Renamed: all-in minimum ships as `min_price_per_kwh_gst_incl` (`routers/public_stations.py:83,156`), not `min_price_per_kwh_all_in`. |

## Confirmed genuinely open (20)

Highest-consequence first.

| Issue | Missing |
|---|---|
| `charger-connectivity-zulip-alerts/01,02,03` | **No Zulip code at all** — `ZulipAlertService`, `ZULIP_BOT_API_KEY`, `ZULIP_SITE` absent. Commit `664574a` ("zulip alerts") contains only PRD + issues, zero code. |
| `release-pipeline/02,04,06` | `make staging-release` / `make prod-release` — **0 occurrences** in the Makefile. |
| `ws-disconnect-tracking/04` | `CLOSE_GRACE_SECONDS` absent; `force_disconnect` still has no `asyncio.wait_for` bound on `websocket.close()`. |
| `ocpi-google-feed/02,03` | No OCPI code anywhere in backend or frontend — feature unstarted. |
| `paytm-migration-investigation/06` | `PaymentProvider` abstraction absent. |
| `billing-all-in-rewire/02` | Synthetic fee still live in `services/tariff_utils.py`; `tariff_drift_check.py` absent. |
| `qr-instant-refund/01,02` | `_wait_for_plug_in_then_start` / `process_payment_captured` absent. |
| `qr-refund-balance-logging/01` | `record_refund_speed` absent (the `refund_speed` hits are the model column — different thing). |
| `franchisee-activation-reconciliation/01` | `FranchiseeActivationReconciliationService` absent. |
| `admin-reports/02,04` | `bucket_start` / `sample_count` / `bucket_start_ist` absent. |
| `active-session-on-my-charges/01` | `STALE_PAYMENT_THRESHOLD_SECONDS` absent. |
| `active-session-on-my-charges/09` | `_classify_sub_state` absent. |
| `diagnostic-bundle-headerless/01` | `_BODY_PREVIEW_CHARS` / `archive_only_lines` absent. |

## Partially done or needs a human read (8)

| Issue | Finding |
|---|---|
| `active-session-on-my-charges/06` | **Split verdict.** `budget_remaining` *has* been dropped from the API (survives only in a test), but `routers/_shared.py` was never extracted. Left open for the remaining half. |
| `prod-deploy-2026-05/03` | Names a `.sql` backup under `/home/ec2-user/...` — an artifact on the prod box, unverifiable from the repo by construction. |
| `qr-regeneration-fix/02` | Flagged only because Razorpay QR ids (`qr_StVw…`) are quoted as examples. A close-on-failure path does exist; needs reading to confirm it is the DB-insert-failure path. |
| `logs-console-correlated-reply/01` | Flagged only on an OCPP message id (`boot_55C1E96E`) quoted as an example. Needs reading. |
| `qr-billing-overhaul-review-fixes/01,02,04,06` | Flagged on proposed **test and fixture names**, which legitimately differ from what ships. Note `_synthetic_fee_split` scaffolding *is* still present, consistent with `billing-all-in-rewire/02` being open. |
