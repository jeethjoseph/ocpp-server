# Active session on `/my-charges`

Show a QR/UPI customer their in-progress charging session(s) on the public `/my-charges` page, so they can see what's happening without needing an account.

## Constraint of record

`docs/adr/0006-public-active-session-read-only.md` — the active-session view is **read-only**. No remote-stop button. The customer's "stop now" path is unplugging the cable; the budget cap auto-stops them when their prepaid balance is exhausted.

## Scope

- **In:** QR-paid (appless) sessions, identified by the customer-typed UPI VPA. List of all in-progress sessions for that VPA. Four sub-states: Waiting to plug in / Charging / Paused / Stopping.
- **Out:** Wallet sessions (already covered by `/my-sessions`). Remote stop. Any action affordances. Stop authentication.

## Customer flow

1. Customer scans the QR sticker → pays in their UPI app.
2. Customer navigates back to `voltlync.com/my-charges` (or already had it open).
3. Customer types the VPA they paid from (or finds it pre-filled from a prior visit) and taps search.
4. Top of results shows one card per active session with live energy / spent / refund-if-stopped-now / power / duration / budget bar.
5. Below it, the existing transaction history list.

## Decisions (from grill 2026-05-21)

- **Sub-states:** all four surfaced with state-conditional copy.
- **Multi-session:** list rendering; degenerates to single card in the common case.
- **`PAID`-no-txn rendering gate:** same threshold as the stale-payment watchdog.
- **No action affordances** (per ADR 0006).
- **Card fields** (Charging / Paused / Stopping): energy delivered (kWh), spent so far (₹), refund if stopped now (₹), power draw (kW), duration (client-side 1s tick), budget bar.
- **Waiting state:** "₹X paid · waiting to start" + plug-in helper copy + auto-refund window callout.
- **Polling:** 15s while the tab is visible; pause via `document.visibilityState`.
- **Layout:** active card at top of VPA search results, above the status filter.
- **VPA persistence:** `localStorage["voltlync.lastVpa"]`, pre-fill but don't auto-search.
- **Backend:** new endpoint `GET /api/public/qr-active-sessions?vpa=X` returning a list. Reuses `qr_session:{txn_id}` Redis cache for tariff/fee/budget; reads latest `MeterValue` for live energy and power. Same 20 req/60s/IP rate limit as the history endpoint.

## Slices

1. `01-backend-qr-active-sessions-endpoint.md`
2. `02-frontend-active-session-card.md`
3. `03-vpa-localstorage-persistence.md`
