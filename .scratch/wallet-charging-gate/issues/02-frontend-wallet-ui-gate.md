# 02 — Frontend wallet UI gate (cosmetic)

Status: ready-for-human

## Why

Pure UX: don't show a button or modal that the backend will 403. Independent of
issue 01's runtime behaviour (the backend is already safe without this), but uses
the same flag name. Can be grabbed in parallel with 01.

## What

Introduce `NEXT_PUBLIC_WALLET_CHARGING_ENABLED` (default `true`) and hide the
wallet entry points when off.

### Tasks

1. **Read the flag.** `process.env.NEXT_PUBLIC_WALLET_CHARGING_ENABLED !==
   'false'` (default-on; empty/unset → enabled). Centralise in one small helper
   so the checks don't drift.
2. **Hide "start with wallet."** On `frontend/app/charge/[id]/page.tsx`, hide the
   wallet remote-start CTA when off. Leave any QR/scan path visible.
3. **Hide top-up.** Hide the recharge entry point
   (`frontend/components/WalletRechargeModal.tsx` trigger, and the wallet
   balance/top-up affordance on `frontend/app/page.tsx`) when off. Balance may
   still be displayed read-only (existing balances are frozen, not hidden — see
   PRD).
4. **Dockerfile build-arg.** In `frontend/Dockerfile` builder stage, add
   `ARG NEXT_PUBLIC_WALLET_CHARGING_ENABLED` and
   `ENV NEXT_PUBLIC_WALLET_CHARGING_ENABLED=$NEXT_PUBLIC_WALLET_CHARGING_ENABLED`.
5. **Compose build.args.** Add `NEXT_PUBLIC_WALLET_CHARGING_ENABLED:
   ${NEXT_PUBLIC_WALLET_CHARGING_ENABLED:-true}` to `frontend.build.args:` in
   `docker-compose.staging.yml` and `docker-compose.prod.yml`.
6. **Env examples.** Add to `frontend/.env.example` and the Frontend section of
   `.env.staging.example` / `.env.prod.example`.

## Acceptance criteria

- `cd frontend && npm run build` passes (full production build, per CLAUDE.md —
  not just tsc/lint).
- With the var `false` at build time: no top-up modal, no "start with wallet"
  CTA; QR/scan path still present; admin wallet pages unaffected (admin is a
  separate surface).
- With the var unset/`true`: UI unchanged from today.
- Post-build sanity: the baked bundle reflects the flag (grep a chunk, or verify
  the gated UI is absent in the running container).

## Notes

This is build-time only — re-enabling later requires a frontend rebuild. That is
acceptable because re-enable is gated on a deliberate ledger deploy (ADR 0011).

## Comments

### Implemented (awaiting review/merge)

- **Helper**: `frontend/lib/feature-flags.ts` → `walletChargingEnabled()`
  (`process.env.NEXT_PUBLIC_WALLET_CHARGING_ENABLED !== "false"`, default on).
- **Start-with-wallet**: `app/charge/[id]/page.tsx` — folded the global flag into
  the existing `walletDisabled` (`|| !walletChargingEnabled()`), so it reuses the
  already-present disabled-button + "scan the QR code instead" messaging. No new
  UI invented.
- **Top-up**: `app/my-sessions/page.tsx` — "Recharge Wallet" button hidden when
  off; **balance card stays visible** (Q3: existing balances remain shown).
- **Home** (`app/page.tsx`): only descriptive copy mentions wallet; no top-up
  affordance there → no change needed.
- **Dockerfile**: added `ARG`+`ENV NEXT_PUBLIC_WALLET_CHARGING_ENABLED` in the
  builder stage.
- **Compose build.args**: added `NEXT_PUBLIC_WALLET_CHARGING_ENABLED:-true` to
  `frontend.build.args` in staging + prod compose.
- **Env examples**: added to `frontend/.env.example`, `.env.staging.example`,
  `.env.prod.example`.

### Verification

- `cd frontend && npm run build` → **passed** (all 35 routes compiled; full
  production ruleset, not just tsc/lint).
- Runtime "flag=false actually hides the UI" check is deferred to **issue 03**,
  where the var is set `false` for real and verified in the deployed container
  (issue 03 checklist already covers it). Avoids a redundant second full build
  here; the gating logic reuses the proven `walletDisabled` path.
