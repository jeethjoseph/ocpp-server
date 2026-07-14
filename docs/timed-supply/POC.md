# Timed Supply — 2-Week POC

**Goal:** prove the *one uncertain thing* — the **connectivity-gated, server-metered
session loop** (ADR-0001) — end-to-end, **switching a real relay**. Everything else
is faked or cut. Throwaway scaffolding that becomes the v1 skeleton, not v1 itself.

## What the POC must prove (success criteria = the demo script)

A single clickable demo, with a **physical relay** (driving an LED or a small
appliance) as the Machine:

1. The relay device connects and heartbeats → app shows "available".
2. Wallet shows a seeded balance (₹100). Tap **Start** → **the relay physically
   closes** (supply on), **live timer + running cost** tick up.
3. Tap **Stop** → **relay opens**, session ends, wallet **debited** by
   `rate × seconds`, receipt shows seconds + amount.
4. **Budget cap:** seed a low balance → server **auto-stops** and the relay opens at
   `max_on_seconds`.
5. **The core proof — connectivity gating:** mid-session, **pull the relay device's
   network/power link** → the on-board watchdog **opens the relay** (supply off) and
   the server marks the session **suspended, billing frozen**. Reconnect within the
   window → session **auto-resumes, relay closes again**, and the **offline gap is
   not billed**.

If that demo runs, ADR-0001 is validated on real hardware and the riskiest part of
v1 is de-risked.

## Stack (minimal — optimise for build speed, not production)

- **Backend:** FastAPI + Tortoise + **SQLite** (no postgres/Redis — in-memory
  connection registry, single process is fine for a POC).
- **Device link:** minimal **custom JSON-over-WebSocket** (connect, heartbeat,
  start, stop, status) — not OCPP.
- **The relay device:** an **actual relay** on a microcontroller/Raspberry Pi
  (ESP32 + relay module, or Pi + relay HAT) running a **throwaway "relay-agent"** we
  write for the POC — connects, heartbeats, honours remote start/stop, and **opens
  the relay on link loss** (the watchdog). *This is a POC stand-in for the firmware
  the device team will build to protocol 2.7 — not the production firmware.*
- **Client:** thin **Vite + React web** app (one or two screens). **Not** Capacitor,
  **not** app-store.
- **Auth:** hardcoded single demo user. **No Clerk.**
- **Payments:** a `POST /wallet/topup` that just credits the ledger. **No Razorpay.**

## Explicit cut list (NOT in the POC)

Production firmware / custom PCB · native app · app store · Clerk · real Razorpay ·
invoices · admin console (seed via API/DB) · map + geolocation (use a machine
**list**) · QR scanning · multi-operator / settlement · Redis · staging/prod infra ·
Aerich migrations (recreate the DB) · full test suite (only the ~4 session-engine
tests below).

## Day-by-day (10 working days, 1 builder + Claude)

| Day | Deliverable |
|---|---|
| 1 | Scaffold: FastAPI + Tortoise/SQLite, models (`Machine`, `SupplySession`, `Wallet`, `WalletTransaction`), config. Vite/React shell. |
| 2 | Device WS protocol + in-memory registry + heartbeat + status. **Relay-agent + hardware bring-up** (wire the relay; connect, heartbeat, honour start/stop, open-on-link-loss). |
| 3 | Remote start/stop dispatch + ack → **relay physically switches**; `SupplySession` lifecycle. |
| 4 | **Server-side per-session ticker** — accrue connected-on seconds; live session state. |
| 5 | Billing on stop (`rate × seconds`), wallet debit, receipt; balance = SUM(ledger); fake top-up. |
| 6 | **Budget-derived `max_on_seconds` cap → auto-stop** (relay opens). |
| 7 | **Disconnect → suspend → freeze billing; resume within 30-min window → relay auto-closes; finalize past window.** |
| 8 | Web client: machine list, Start/Stop, **live timer + cost**, wallet, session history/receipt. |
| 9 | Integrate; demo-script the 5 criteria (incl. pulling the physical link); edge cases (double-start, stop-while-disconnected). |
| 10 | Buffer, cleanup, short README + recorded demo. |

## Key POC tests (the only ones worth writing now)
- Start→accrue→stop bills `rate × seconds` and debits the wallet.
- Budget cap auto-stops at `max_on_seconds`.
- Disconnect freezes billing; the off-gap is excluded from billable seconds.
- Reconnect inside the window resumes; outside it finalizes.

## What the POC deliberately leaves unproven
Production firmware robustness, native/app-store UX, real payment flow, formal
invoicing, scale/concurrency of the per-session ticker, and **zero-supply
blindness** (still unmeasurable — a product-acceptance question, not something a POC
can resolve). These stay in [`PROJECT-PLAN.md`](./PROJECT-PLAN.md) §1.
