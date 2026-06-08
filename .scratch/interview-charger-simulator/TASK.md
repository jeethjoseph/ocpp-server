# Take-Home: OCPP 1.6 Charge Point Simulator

## Background

We operate a CSMS (Charging Station Management System) — a backend that real EV
charging stations connect to over WebSockets using the **OCPP 1.6 (JSON over
WebSocket)** protocol. The charging station ("charge point") is the client; our
server is the central system.

We have a live **staging** server you can connect to. Your task is to build a
**charge point simulator**: a program that behaves like a real charging station,
connects to our staging server, and drives a complete charging session end to
end.

This is the same kind of tool our team uses daily to test the server without
physical hardware. We want to see how you approach an unfamiliar protocol, model
a stateful long-lived connection, and produce something we'd actually be
comfortable running.

## What you're connecting to

- **WebSocket URL:** `wss://staging.voltlync.com/ocpp/{charge_point_id}`
  - The charge point ID is the **last path segment** of the URL.
  - You must use a charge point ID that is **already registered** on staging —
    the server rejects unknown IDs at connection time. We will give you a
    registered ID (and a backup) when you start.
- **Protocol:** OCPP 1.6, JSON variant, over a standard WebSocket. The WebSocket
  subprotocol is `ocpp1.6`.
- The server is the **central system**; your simulator is the **charge point**.
  That means your simulator both *sends* requests (e.g. it reports its status)
  and *receives* requests from the server (e.g. the server tells it to start a
  transaction) — you must handle both directions.

## The protocol — read the spec

We are deliberately **not** spelling out the wire format. Part of this exercise
is reading a real-world protocol spec and implementing against it. OCPP 1.6 JSON
is well documented; the **OCPP 1.6 JSON specification** (the Open Charge Alliance
"OCPP 1.6 Edition 2" document, JSON section) is the authoritative source. A web
search for "OCPP 1.6 JSON specification" will find it.

Things the spec will tell you that you'll need to get right:

- The four message types and their array framing (CALL, CALLRESULT, CALLERROR),
  including the message type IDs and the unique message ID field.
- How a request is correlated to its response, and what a CALLERROR looks like.
- The payload schema for each message you send or receive.

## What your simulator must do

Implement enough of a charge point to drive a **full, successful charging
session**, plus the server-initiated control messages that session depends on:

1. **Boot** — On connect, announce the charge point to the server and honour the
   response (it tells you a heartbeat interval and the server's clock).
2. **Heartbeat** — Keep the connection alive on the interval the server gave you.
3. **Status reporting** — Report status transitions as the session progresses
   (a real charger moves through states like *Available → Preparing → Charging →
   Finishing → Available*).
4. **Remote start** — The server will send your simulator a request to *start* a
   transaction. Respond correctly, then open the transaction and begin charging.
5. **Metering** — While charging, periodically send meter readings. Energy
   delivered must increase monotonically over the session (it never goes
   backwards).
6. **Remote stop** — The server will send a request to *stop* the transaction.
   Respond correctly, close the transaction, and return to an idle state.
7. **Reset** — Handle a reset request (soft/hard) by acknowledging it and
   simulating a reboot (disconnect, then reconnect and boot again).

A correct run, observed from the server side, should look like a real charger
that booted, was remotely started, charged for a while, was remotely stopped,
and went back to available.

### A note on concurrency

This is a long-lived, bidirectional connection. The server may send you a request
*while you are waiting for a response to a request you just sent*. Your simulator
must not deadlock or mis-correlate responses when that happens. How you handle
this is one of the more interesting parts of the task — think about it.

## Constraints & expectations

- **Language:** Your choice. Pick what you're fastest and cleanest in. (Our
  backend is Python, so Python is welcome but not required.)
- **Libraries:** Use whatever you like for the WebSocket transport. We'd prefer
  you implement the **OCPP message handling / correlation yourself** rather than
  leaning on a full OCPP framework that does it for you — that's the part we want
  to see you reason about. A raw WebSocket client library is fine.
- **Configurable:** Charge point ID and server URL must be configurable (CLI
  flag, env var, or config file — your call), not hardcoded.
- **Clean shutdown:** Ctrl-C should close the connection gracefully.
- **One caveat about reconnecting:** if you disconnect and immediately reconnect
  with the same ID, the server may briefly reject you (it guards against
  reconnection races). Back off a few seconds before reconnecting and you'll be
  fine. Handle the rejection without crashing.

## Deliverables

1. **Source code** for the simulator.
2. **A README** that covers:
   - How to install dependencies and run it (exact commands).
   - What it does and the session flow it produces.
   - Any decisions or trade-offs you made, and anything you'd improve with more
     time.
3. Send us a git repo (or a zip) — whatever's easiest.

## Stretch goals (optional — only if you have time)

These are not required to pass. Pick any that interest you:

- Simulate a fault during charging and report it, then recover.
- Make the charging behaviour realistic (ramp-up power, configurable target
  energy or duration, a tariff-shaped power curve).
- Drive multiple simulated chargers concurrently from one process.
- Structured logging or a small live status display of the session.
- A short test or two around your message-framing / correlation logic.

## How we'll evaluate it

We care most about: **does it actually work against staging**, is the protocol
handling **correct** (framing, message-ID correlation, both directions), is the
concurrency handled soundly, and is the code **clear and well-organised**. A
focused, correct, well-explained simulator beats a sprawling one with half-working
extras.

## Getting help

If something about the *server* behaves unexpectedly (it rejects you, drops the
connection, doesn't respond), tell us what you sent and what you saw — debugging
an integration against a system you don't fully control is part of the job, and
how you ask is informative. Don't ask us how to read the OCPP spec; do ask if you
think staging is misbehaving.

Good luck — we're looking forward to seeing it run.
