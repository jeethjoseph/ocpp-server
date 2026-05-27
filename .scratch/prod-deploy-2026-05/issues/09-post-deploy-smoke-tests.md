Status: ready-for-human

# Post-deploy smoke tests + 24-48h observation

## What to build

User-flow verification of the features that shipped in this deploy, plus a passive observation window watching Sentry, NR, and CloudWatch for emergent issues. **This is the final gate before declaring the deploy successful.**

If serious issues surface here, refer back to issue 04's rollback section.

## Prerequisites

- [ ] Issues 04, 05, 06, 07, 08 all complete
- [ ] Admin Clerk session available for testing
- [ ] (Optional) Test charger available for E2E OCPP testing

## What to test (in rough priority order)

### A. Admin UI — basic feature sanity (~20 min)

| Feature | What to verify | How |
|---|---|---|
| Chargers list | Loads, status pill renders, availability toggle responds | `/admin/chargers` — click a toggle, refresh, confirm flip |
| Availability toggle on a real charger | OCPP message sent + `Charger.availability` persists | Click toggle; check `audit_log` for `charger.availability_changed`; verify `availability` column flipped |
| Stuck settlements page | Loads, "Mark BELOW_THRESHOLD" + "Mark SETTLED" buttons render correctly | `/admin/settlements/stuck` — if any rows exist, eligibility check should match payout amount |
| Franchisee detail page | Settlement Ledger table includes the new terminal-action buttons per row | `/admin/franchisees/<id>` — Settlement Ledger card |
| Firmware page | Loads, list shows existing firmware, upload accepts a file | `/admin/firmware` — upload a small test binary |
| GST invoices admin page | Loads, recent invoices render with new fields (place_of_supply_state_code, series, etc.) | `/admin/gst-filings` (or wherever invoices live) |

### B. Customer-facing — non-destructive sanity (~10 min)

| Feature | How |
|---|---|
| `/my-charges` loads (public, no auth) | Try with a known UPI VPA from prod |
| Active session card renders (if there's a live charging session) | Same page with an active session |
| QR scan + payment flow | DON'T trigger a real payment. Just verify the scanner page loads and a QR endpoint returns sensible JSON for a known charger |

### C. Backend smoke tests (~10 min)

```bash
# OCPP traffic flowing
sudo docker logs ocpp-backend-prod --since 5m 2>&1 | grep -iE "Heartbeat|StatusNotification|BootNotification" | wc -l
# Expected: > 10 in 5 min (depends on charger count)

# No spike of new errors since deploy
sudo docker logs ocpp-backend-prod --since 30m 2>&1 | grep -iE "ERROR|FATAL|exception|traceback" | head -20
# Expected: empty or only known-benign warnings

# Sentry receiving events at production env
# Check Sentry UI: production env should show a recent event timestamp
# (Even if no errors, normal traces/logs land there with logging integration)

# New Relic APM showing the new app
# Check NR UI: "OCPP-Server-Production" should appear in APM & Services
# Verify it's receiving transactions
```

### D. Migration-specific behavior verification (~15 min)

For each major migration that shipped, verify the user-visible aspect:

| Migration | What to check |
|---|---|
| 32 + 33 (wallet ledger) | Get a known customer's wallet balance via API, compare to manual SUM via psql — must match |
| 27-30 (GST overhaul) | Most recent GST invoice has populated supplier_gstin, place_of_supply_state_code, gateway_charges fields |
| 35 (firmware state machine v2) | Existing firmware updates page shows their state correctly (no orphan rows) |
| 36 (tariff all-in column) | A tariff in the system shows `tariff_per_kwh_all_in` populated and `rate_per_kwh` ~2% lower than before |
| 41 (drop qr_code unique) | Try creating a charger that previously would have hit a uniqueness conflict (or skip — additive change) |
| 42 (availability column) | Per check A above — toggle reflects column, not status |

### E. The OCPP E2E test (optional but recommended)

If you have access to a real charger or simulator pointed at prod:

1. Trigger a StartTransaction
2. Send a few MeterValues frames
3. Send a StopTransaction
4. Verify:
   - Transaction lands in DB with sensible energy + cost
   - GST invoice is generated and uploaded to `voltlync-invoices-prod` S3 bucket
   - Customer wallet was debited correctly (CHARGE_DEDUCT row with positive amount)
   - The full ledger SUM matches the wallet balance shown in admin UI

### F. The 24-48h passive observation

For the next 24-48 hours, watch (no active polling required — set alerts):

| Watch | Where |
|---|---|
| Sentry exception rate | Sentry "production" env — should be flat or trending down |
| NR APM error rate | NR `OCPP-Server-Production` entity |
| NR APM latency (p50/p95/p99) | Should be within ~10% of pre-deploy baseline (we don't have a clean baseline — but a 2x spike is a problem) |
| CloudWatch RDS-equivalent: backend container CPU/memory | EC2 metrics — no spike vs pre-deploy |
| Stuck-payout detector firing? | Sentry "Stuck franchisee payouts" alerts — should NOT fire for previously-stuck entries (we backfilled in issue 07) |
| Wallet negative-balance custom metric | NR `Custom/Wallet/NegativeBalance` — should be ~0 events |
| OCPP heartbeat rate | NR `Custom/OCPP/Messages/IN/Heartbeat` — steady |
| Disk usage on prod EC2 | Should be flat (log rotation isn't enabled on staging-style anchor on prod — prod has per-service rotation already) |

## Triggers for rollback

ANY of the following → roll back per issue 04:

- Backend won't stay up (`docker ps` shows restart-loop)
- 5xx error rate on `/api/*` endpoints > 10% sustained
- Migration corruption found (e.g. wallet sums diverging from reality)
- GST invoices failing to generate for new sessions (legal/compliance)
- A real customer-impacting incident attributable to the deploy

If any single feature is broken but the system is otherwise healthy — log it as a follow-up bug, don't roll back the whole deploy.

## Definition of done

- All A + B + C + D checks pass
- (Optional) E test passed against a real or simulated charger
- Zero unexpected error spikes in F observation window over 24h
- Stuck-payout detector has fired at least once without alerting on previously-stuck entries
- Any follow-up bugs filed as separate issues
- Operator sign-off: "deploy successful, no rollback needed"
