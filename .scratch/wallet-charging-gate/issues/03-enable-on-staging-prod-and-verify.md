# 03 — Set flag on staging/prod + verify

Status: ready-for-agent

## Why

The code from issues 01 and 02 ships with the flag defaulting to `true` (no
behaviour change on merge). This issue is the actual switch-off: set the var to
`false` in the staging/prod env files and roll it out, backend-first.

Depends on: 01 (required), 02 (for clean UX — backend-only is safe but shows a
button that 403s until the frontend redeploys).

## What

1. **Staging first.** Set `WALLET_CHARGING_ENABLED=false` and
   `NEXT_PUBLIC_WALLET_CHARGING_ENABLED=false` in `.env.staging`. Restart backend
   (instant enforcement), then rebuild + redeploy frontend (un-shows the UI).
2. **Verify on staging** (see checklist below).
3. **Prod.** Same change in `.env.prod`, backend restart then frontend rebuild.

### Rollout order (per ADR 0011)

Backend disable is restart-only and takes effect immediately; the frontend hide
rides the next build. A stale frontend is safe (clean 403), so backend-first is
correct.

## Verification checklist (run on staging, repeat on prod)

- `docker exec <backend> env | grep WALLET_CHARGING_ENABLED` → `false`.
- Calling `remote_start_charging` / `remote_start_by_string_id` / top-up returns
  403.
- Start a **QR session** end to end → still works and settles to the franchisee
  (Route split unaffected).
- An in-flight wallet session (if any) completes and bills at StopTransaction.
- Admin wallet pages still render balances (frozen balances visible).
- Frontend (post-redeploy): no top-up modal, no "start with wallet" CTA; scanner
  path intact.

## Re-enable (future, not this issue)

Tracked by ADR 0011's re-enable gate: build pooled-settlement ledger → activate
Razorpay Direct Transfer → `WALLET_SETTLEMENT_ENABLED=true` (backfill `ON_HOLD`)
→ `WALLET_CHARGING_ENABLED=true` (backend restart + frontend rebuild).

## Comments
