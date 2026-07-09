# Session resume — pick up after full system restart

Status: ready-for-agent
Branch: `72-ocpi-221-cpo-feed-publish-chargers-to-google-maps` (all changes are **uncommitted working-tree** edits — a reboot does NOT lose them; files + the local Docker DB volume persist).

## Why we stopped
Host disk hit **99% full** (~2.7 GB free of 228 GB) and the dev containers went down and wouldn't restart (native `redis`/`postgres` on the host hold ports **6379/5432**). This is an environment issue, not a code issue — TypeScript "Compiled successfully" throughout; the build only failed on an `ENOSPC` write during static export. User is restarting the whole system.

## First actions after restart (in order)
1. **Confirm disk freed:** `df -h /System/Volumes/Data` — need comfortably more than a couple GB.
2. **Bring the dev stack up.** If containers still fail on port bind, the host's native redis/postgres are the conflict — stop them (or don't auto-start them), then:
   `docker compose up -d postgres redis backend frontend`
3. **Migrations:** the backend entrypoint auto-runs `aerich upgrade` on boot. Migration **47** (`tariff_unique_charger`) was already applied to the local DB in the prior session, so this should be a no-op — verify with `docker exec ocpp-postgres psql -U ocpp_user -d ocpp_db -Atc "SELECT indexname FROM pg_indexes WHERE tablename='tariff';"` → expect `uid_tariff_charger_081d1b`.
4. **Run the backend tests that never got to run + regression the rest:**
   ```
   docker exec ocpp-backend pytest \
     tests/test_socket_classification.py \
     tests/test_qr_receipt_card_breakdown.py \
     tests/test_tariff_unique_charger.py \
     tests/test_start_transaction_no_vehicle.py \
     tests/test_chargers.py \
     tests/test_public_qr_transactions.py \
     tests/test_invoice_service.py
   ```
   (Run per-file, not one bare `pytest` — see CLAUDE.md baseline-flake note.)
5. If all green → mark task tracker #3 and #4 done; the three issues below are fully complete.

## Work status

### DONE — upsert-race-hardening (prior session, tests ran green)
- Issue 01 (Tariff `UNIQUE(charger_id)` dedup migration + race-safe upsert) — implemented, migration 47 applied locally, 5 tests green.
- Issue 02 (drop placeholder VehicleProfile in StartTransaction) — implemented, 2 tests green.

### DONE & VERIFIED — bill-card-consistency issue 01
- **Task 1 (bill energy):** `invoice_service.py` energy render `:.1f` → `:.3f`. Invoice tests (20) green.
- **Task 2 (card = bill):** `routers/public_qr_transactions.py` now builds the breakdown from the reconciled `gst_invoice` via `_customer_breakdown` (synthetic-split fallback), and **dropped** `platform_fee`/`razorpay_commission`/`razorpay_gst`/`fee_source` from the customer response (ADR 0001). Frontend `QRTransactionItem` + `TransactionCard` show `gateway_fee` and energy at `toFixed(3)`. **7 backend tests green + `npm run build` passes.**

### CODE DONE, FRONTEND VERIFIED, BACKEND TESTS UNRUN — socket-charger-classification issue 01
- **Frontend (verified):** `lib/utils.ts` `isSocketCharger` taxonomy; Edit-Charger `connector_type` `<select>`; `Charger.connectors` + `ChargerUpdate.connector_type` + `CONNECTOR_TYPE_OPTIONS` types. **vitest 17/17 green, `npm run build` passes.**
- **Backend (syntax-clean, UNRUN):** shared taxonomy `is_socket_connector_type` in `charger_type_service.py` (gates BOTH the button and the real remote-start endpoint); `ChargerUpdate.connector_type` + `ALLOWED_CONNECTOR_TYPES` validation + persist to connector(s) in `update_charger`; charger **list** now returns `connectors` (bulk query; `ChargerResponse.connectors` + `charger_to_response(..., connectors=...)` + `ChargerResponse.model_rebuild()`). **`py_compile` clean; `tests/test_socket_classification.py` written but not executed.** ← the one thing left to verify.

## Files changed this session (all uncommitted)
Backend:
- `services/invoice_service.py` — energy `:.3f`
- `routers/public_qr_transactions.py` — `_customer_breakdown`, invoice-sourced, ops-fee fields removed
- `services/charger_type_service.py` — `SOCKET_CONNECTOR_TYPES` + `is_socket_connector_type`
- `routers/chargers.py` — `ALLOWED_CONNECTOR_TYPES`, `ChargerUpdate.connector_type`, connector_type persist, `ChargerResponse.connectors` + `charger_to_response` connectors + `model_rebuild()` + list bulk-fetch
- (prior session) `models.py` Tariff `unique_together`, `migrations/models/47_20260703082906_tariff_unique_charger.py`, `_upsert_charger_tariff` guard, `main.py` StartTransaction vehicle removal
- New tests: `tests/test_socket_classification.py` (UNRUN), `tests/test_qr_receipt_card_breakdown.py`, `tests/test_tariff_unique_charger.py`, `tests/test_start_transaction_no_vehicle.py`

Frontend:
- `lib/utils.ts`, `lib/api-services.ts`, `types/api.ts`, `app/my-charges/_components/TransactionCard.tsx`, `app/admin/chargers/page.tsx`, `__tests__/lib/utils.test.ts`

## Not started / parked (per user "no need" earlier — do NOT file unless asked)
- **Pricing-model change** (charge 2% gateway on *consumption* not *prepay*, so `energy × tariff = total`): sized at ~₹43 net absorption on prod, easy-yes economics, but a commercial decision + ADR-0001 supersede. Parked.
- **65 blank-billing prod sessions** (Mar–May, `total_billed`/`energy_charge` NULL on COMPLETED refunded QR; apparent ~₹1,700 under-collection, uncertain vs session-time tariff; appears already fixed post-2026-05-30). Parked — needs its own investigation.
- **50% `fee_source = null` gap** on prod QR payments (real Razorpay fee captured on only ~half). Parked.

## Cleanup note
Removed my own throwaway artifacts to free disk: `.scratch/plot-venv/`, `~/.cache/matplotlib`, `frontend/.next` (regenerated by build). No user data touched.
