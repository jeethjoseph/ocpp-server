# Timed Supply Control System — Project Plan (v1)

**Status:** draft for sign-off · **Date:** 2026-07-09 · Working name only.

A greenfield product: customers find a **Machine** on a map (or scan its QR), start
it from a native app, it delivers a **safe low-voltage supply** while on, and they
are billed for the **connected-on seconds**, deducted from a prepaid **Wallet**.
Unattended, single-operator, pure-time (no flow sensor). **Device hardware and
firmware are delivered by separate teams** — our scope is the server, the apps, and
the device WS protocol we hand them as the interface contract.

The VoltLync EV-CSMS in this repo is the **reference architecture** — we reuse its
*patterns* (WebSocket device link, event-sourced wallet, Redis liveness registry,
Clerk auth, Capacitor app, Next.js admin) but write fresh code. See
[`CONTEXT.md`](./CONTEXT.md) for the glossary and
[`adr/0001-connectivity-gated-server-metered-supply.md`](./adr/0001-connectivity-gated-server-metered-supply.md)
for the one load-bearing decision.

---

## 0. Decisions already locked

| # | Decision | Rationale |
|---|---|---|
| D1 | **Greenfield**, EV code is reference only | Different billing model |
| D2 | **Server-metered wall-clock time**, no device counter | Time has no meter (ADR-0001) |
| D3 | **Connectivity-gated supply** — relay opens on link loss | Closes the offline-unbilled-supply safety hole (ADR-0001) |
| D4 | **Bill only connected-on seconds**; off-gaps unbilled (exact) | Supply is physically off when disconnected |
| D5 | **30-min resume window**; **auto-re-energize** on reconnect | Safe: supply is safe-low-voltage + unattended |
| D6 | **Pure-time, no sensor** → *zero-supply blindness accepted* | See Q-C3 |
| D7 | **Wallet-only** funding; QR = machine-selector, not guest-pay | Simplest v1 |
| D8 | **Single operator** (all machines owned) → **no settlement layer** | Removes ~30% of EV scope |
| D9 | **Native Capacitor customer app + Next.js admin + Clerk** | Wireframe demands native; reuse proven stack |
| D10 | **Hardware + firmware owned by separate teams**; we own the **device WS protocol** as the interface | Out of our workstream; we deliver the contract they build to |
| D11 | **Pricing is per-machine, controllable from the admin UI** | Operator tunes rates without a deploy |
| D12 | **Defer**: QR/UPI-guest, formal invoicing, OCPI/external feed | Not needed for v1 |

---

## 1. Clarifying questions

Grouped by how much they move the design. **Bold = blocks the estimate or the
architecture.**

### A. Device interface (coordinate with the hardware/firmware team)
- **A1. Confirm the firmware honours the ADR-0001 contract:** relay + heartbeat +
  a **watchdog that opens the relay on link loss** + remote start/stop. The whole
  billing model rests on this.
- A2. **Heartbeat interval?** Sets metering granularity + how fast a disconnect is
  detected. *(Propose ~15–30s.)*
- A3. **Watchdog "open-on-link-loss" timeout** — seconds of no server ping before
  the relay opens. *(Propose ~10s; must be < heartbeat × 2.)*
- A4. Agree the **device WS protocol** shape — custom JSON-over-WSS (connect,
  heartbeat, start, stop, status). *(We propose; they implement.)*
- A5. **Provisioning** at manufacture: auth key + fixed GPS coords + QR sticker
  loaded onto each unit.

### B. Billing / pricing
- **B1. Rate unit — per second or per minute?** Drives the ticker cadence and how
  the rate is stored/displayed. *(Recommend: meter internally in **seconds**, admin
  enters **₹/min**, bill `seconds × rate/60`.)* Couples with Q-D1.
- B2. Confirm **per-machine rate set in admin** (D11). Any **global default**, and a
  **flat start fee / free grace seconds / minimum charge / rounding rule**?
  *(Recommend: per-machine rate, no minimum, round to the paisa at stop.)*
- B3. **Max session duration / safety ceiling** independent of wallet budget?
- B4. Overshoot: a customer can exceed budget by a few seconds between ticks →
  wallet dips slightly negative. Clamp, absorb, or block? *(Recommend absorb +
  observe, mirroring the EV negative-balance posture.)*

### C. Product / supply
- **C1. What is the supply, concretely?** Needed for app copy, the "picture of
  machine" screen, safety labelling, and to confirm the safe-low-voltage +
  unattended envelope holds for **every** machine (ADR-0001 depends on it).
- C2. Is a session ever controllable from a **physical button on the machine**, or
  strictly app-only? *(Unattended ⇒ recommend app-only.)*
- **C3. Accept zero-supply blindness?** With no sensor, a customer pays for on-time
  even if the thing behind the relay was dead. Accept, or fund a flow sensor
  (changes the architecture toward device-metering)?

### D. Usage & scale (drives the ticker design and capacity)
- **D1. What is the average session length?** Seconds, minutes, hours? Sets the
  right rate unit, the ticker cadence, and realistic wallet/top-up sizes.
- D2. Expected **sessions per day per machine**, and **peak concurrent sessions**
  across the fleet? *(Drives the per-session ticker design — Task 2.3.)*
- D3. How many **machines** at launch and at 12 months?
- D4. **iOS + Android both at launch?** Apple/Google developer accounts ready?
- D5. Launch **geography, currency, timezone, languages** (IST assumed per EV
  precedent).

---

## 2. Task breakdown

Six workstreams. Backend and clients run largely in parallel once the device WS
protocol (2.7) and the API contract (3.4) are frozen. Firmware is delivered by a
separate team against protocol 2.7.

### WS1 — Foundations
- 1.1 Repo scaffold, Docker compose (postgres, redis, backend), env plumbing, CI,
  DB SSL pattern (reuse EV `db_ssl.py`)
- 1.2 Data model + Aerich migrations: `Machine`, `SupplySession`, `User`, `Wallet`,
  `WalletTransaction`, `Tariff`, `Receipt`, `MachineAuthKey`
- 1.3 Clerk integration (backend), logging, monitoring baseline

### WS2 — Device link & session engine *(novel, highest-risk core)*
- 2.1 Device WebSocket endpoint + connection manager (in-memory dict + Redis
  liveness mirror) — pattern from `connection_manager.py`
- 2.2 Per-Machine auth on WS upgrade (pattern from ADR-0020) + heartbeat + status
- 2.3 **Server-side per-session ticker** — accrues connected-on seconds, enforces
  the **max-on cap**, fires stop. *Novel vs EV (server owns the clock).*
- 2.4 Session lifecycle: start (snapshot budget → `max_on_seconds`), accrue, stop
  (finalize + bill), remote start/stop dispatch with ack
- 2.5 Disconnect → suspend → **30-min resume** → finalize-past-window; startup
  invariant check `resume_window ≫ heartbeat`
- 2.6 **Device simulator** (headless) for integration tests
- 2.7 **Freeze + document the device WS protocol** → handoff to the firmware team

### WS3 — Wallet, payments & billing
- 3.1 Event-sourced wallet ledger (non-negative amounts, type-directed,
  SUM-derived balance + Redis cache) — pattern from `wallet_service.py`
- 3.2 Razorpay top-up: create order, verify, webhook, idempotency
- 3.3 Billing at stop: `rate × billable_seconds`, wallet debit, **Receipt**
  (simple v1; formal invoicing out of scope)
- 3.4 **Freeze the customer + admin REST API contract** (unblocks WS4/WS5)

### WS4 — Customer native app (Capacitor + Vite + React + Clerk)
- 4.1 Scaffold + Clerk + API client + native plugins (barcode, Razorpay, geolocation)
- 4.2 Map/Home (machine search + markers) · machine-QR Scanner
- 4.3 Machine detail (picture + START/STOP + **live elapsed + running cost**)
- 4.4 Sessions history + Receipt view
- 4.5 Profile + Wallet top-up
- 4.6 App-store builds & submission (iOS + Android)

### WS5 — Admin web (Next.js + Clerk)
- 5.1 Scaffold + Clerk middleware
- 5.2 Machines: list, detail, **provision** (auth-key, coords, QR sticker), liveness
- 5.3 **Rate/pricing config (per-machine, editable in UI — D11)** · Sessions
  console · Users

### WS6 — Infra, hardening, UAT
- 6.1 Staging + prod compose, nginx, managed postgres/redis, deploy pipeline
- 6.2 Backend test suite (lifecycle, billing, ledger, **disconnect/resume**, cap)
- 6.3 Edge-case & load testing via simulator · security review · integration UAT
  with the firmware team's real units

---

## 3. Time estimate

**Assumptions:** ~2 engineers who know the reference architecture (their own).
Firmware/hardware are **not** in this estimate (separate teams). Estimates are
**engineer-weeks (EW)**; calendar assumes parallelism after the device protocol
(2.7) and API contract (3.4) freeze.

| Workstream | EW | Notes |
|---|---:|---|
| WS1 Foundations | 2 | Scaffold, data model, CI, auth |
| WS2 Device link & session engine | **5** | The hard part; 2.3/2.5 are novel |
| WS3 Wallet, payments & billing | 3 | Ledger + Razorpay + billing/receipt |
| WS4 Customer native app | 4 | All screens + native + app-store |
| WS5 Admin web | 2 | Lean, single-operator, editable pricing |
| WS6 Infra, hardening, UAT | 3 | Deploy + tests + integration UAT |
| **Total** | **≈19 EW** | |

**Calendar rollups:**

- **2 engineers, partial parallelism → ≈ 11–13 weeks (~3 months) to production v1.**
- 1 engineer, serial → ≈ 19–22 weeks (~4.5–5 months).
- Add **+2–3 weeks** app-store review buffer (Apple, especially).

**Phasing (2-engineer track):**

1. **Weeks 1–2** — WS1 + freeze device protocol (2.7, → firmware team) and API
   contract (3.4).
2. **Weeks 2–6** — WS2 core (session engine + simulator) ∥ WS3 wallet start.
3. **Weeks 4–9** — WS4 app ∥ WS5 admin against the frozen contract.
4. **Weeks 8–11** — billing close-out, WS6 hardening + UAT.
5. **Weeks 11–13** — deploy, app-store submission, launch buffer.

### Risks that move the number
- **Integration dependency:** the firmware team must deliver units that honour
  protocol 2.7 (esp. the watchdog) on time; our simulator de-risks *our* side, not
  theirs. Slippage there delays field UAT (WS6.3), not our build.
- **↑ +2–4 EW** if the supply turns out **not** uniformly safe-low-voltage /
  attended (Q-C1) — protocol changes for interlocks + a different resume policy.
- **↑ +3–5 EW** if a **flow sensor** is funded to kill zero-supply blindness (Q-C3)
  — reopens the device-metering architecture and the protocol.
- **↓ –2–3 EW** if a **mobile-web PWA** replaces the native app (drops app-store +
  native plugins) — at the cost of camera/QR polish and store presence.

---

## Appendix — reference-architecture mapping

| New component | Borrow the *pattern* from |
|---|---|
| Device WS + connection manager | `backend/core/connection_manager.py`, `routers/ocpp_ws.py` |
| Per-Machine WS auth | ADR-0020 (`Charger Auth Key`) |
| Wallet ledger | `services/wallet_service.py` (event-sourced, SUM-derived) |
| Budget cap → auto-stop | `services/wallet_session_service.py` (**re-timed to seconds**) |
| Disconnect/resume/staleness | `services/transaction_finalizer.py`, ADR-0022 |
| Razorpay top-up | `routers/wallet_payments.py`, `services/razorpay_service.py` |
| Native customer app | `app/` (Capacitor + Vite + React + Clerk) |
| Admin web | `frontend/` (Next.js + Clerk) |
| Deploy / env plumbing | root `docker-compose*.yml`, `CLAUDE.md` env-var checklist |
