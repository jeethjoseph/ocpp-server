# VoltLync Product Roadmap — H2 2026

_Last updated: 2026-07-01_

A rolling delivery plan across the CSMS platform: OCPI/Google visibility, franchisee tooling,
security hardening, revenue features, and a payment-provider evaluation. Timeline is
**AI-accelerated** — estimates assume AI-assisted implementation against a fully-specified
plan (each initiative already has written issues + acceptance criteria and, where warranted,
an ADR).

## How to read this

- **Sizing** is relative (S / M / L), expressed as target windows in weeks — not hard commitments.
- Work is largely **sequential** (one primary initiative at a time), with low-touch and
  externally-gated items running in the background.
- Every initiative is **pre-sliced into tracer-bullet issues** — each slice ships independently
  and is demoable on its own, so the roadmap can absorb interruptions without stalling.
- **Decision gates** (◆) are points where we stop and decide before spending more.

---

## Timeline at a glance

```
        Jul            Aug            Sep            Oct →
        |----|----|----|----|----|----|----|----|----|----
1 OCPI+ #####
2 WS-Sec      ####
3 QR-Stack         ####
4 Reports               #####
--------------------------------------------------------------
P Paytm  >>>> background: refund spike + Paytm commercial talks >>>>  ◆ go/no-go
                                                              └──► [contingent migration epic]
```

`#` = active build · `>>>>` = background / externally-gated · `◆` = decision gate

Phase 1 bundles the in-flight OCPI feed with two small franchisee quick wins.
The franchisee analytics graphs move to Phase 4, next to the admin Reports work they share
an aggregation pattern with.

---

## Phase 1 — Ship in-flight, make visible, quick wins (early–mid July)

### 1a. OCPI CPO feed → Google Maps  · **L** · _in flight (current branch)_
Publish chargers to Google Maps via a standards-compliant OCPI 2.2.1 CPO feed (Versions +
Credentials + Locations, real-time availability). This is the branch already in progress;
finishing it puts our network on Google Maps.
- **Value:** discoverability → footfall at franchisee sites.
- **Issues:** 5 (identity/schema → feed scaffolding → locations + status fusion → admin publish toggle backend → frontend). ADRs 0015 / 0016 already written.
- **Milestone:** first charger live on Google Maps (staging canary → prod).

### 1b. Franchisee portal: remove Gross → Power Consumed (kWh)  · **S** · _quick win_
Stop surfacing platform "Gross" anywhere in the franchisee portal; replace the settlement-table
Gross column with Power Consumed (kWh), and strip the Gross fields from the franchisee API.
- **Value:** cleaner, trust-building franchisee view (payout + energy, not platform internals).
- **Issues:** 1 (from the franchisee-dashboard set). Data already on the wire — display + API trim.

### 1c. `/my-charges` role-aware header + smart sign-in routing  · **S** · _quick win_
Give the public `/my-charges` page a minimal header: a Dashboard link back to their portal for
signed-in admin/franchisee users, and post-sign-in routing that sends staff to the right home
(customers stay put).
- **Value:** removes a dead-end for staff who land on the customer page; small polish, low risk.
- **Issues:** 1 (from the franchisee-dashboard set). Reuses existing role/routing logic.

### ▶ Kick off in the background now: Paytm evaluation (see Phase P)
The Paytm commercial/compliance conversation is **externally gated** (depends on Paytm's team),
so we start that clock on day one rather than when we're "ready."

---

## Phase 2 — Security hardening (late July)

### 2. Charger WebSocket authentication  · **M** · _high priority_
Close an **active** vulnerability: today any party that knows a charger ID can impersonate it
over the OCPP WebSocket — inject fake sessions, corrupt billing, and knock the real charger
offline. We add OCPP 1.6 Security Profile 2 (WSS + per-charger Basic Auth), enforced per-charger
with a safe migration path.
- **Value:** eliminates charger spoofing / targeted DoS; protects billing integrity.
- **Issues:** 5 (handshake auth + schema → per-charger enforcement → provisioning/rotation → global enforce flag → nginx rate-limiting follow-up). ADR 0020 written.
- **Note:** this is risk-reduction, not a feature — it can be **pulled forward ahead of Phase 1**
  if we judge the spoofing exposure urgent. Flag for the team.

---

## Phase 3 — Revenue & convenience (early–mid August)

### 3. Stackable QR payments  · **M**
Let a customer top up an in-progress appless charge by paying again — charging continues with no
interruption — instead of the payment being rejected and refunded. Same-payer only (safe);
one continuous session, budget extended, LIFO refund of anything unused.
- **Value:** removes a real drop-off (customer can't extend a session today); more kWh sold.
- **Issues:** 4 (same-payer top-up → durability fix → LIFO refund → customer "pay again" hint). ADR 0021 written.

---

## Phase 4 — Analytics & reporting (late August)

Grouped because the admin Reports and franchisee dashboard graphs **share the same time-bucketing
(`date_trunc`) aggregation** — building them adjacent reuses that work.

### 4a. Admin Reports tab (Temperature first)  · **M**
A top-level admin Reports surface with a subreport framework. Ships the Temperature report first
(modem/board temperature over days/weeks with min–avg–max bands + CSV export), with Energy, Signal,
and Sessions/revenue subreports framed for later.
- **Value:** historical operational insight (thermal trends, fleet health) live tiles can't give.
- **Issues:** 5 (ADR/framework → aggregation endpoint → tab + chart → CSV export → docs).
- **Extensible:** the subreport framework is the reusable investment; later reports are incremental.

### 4b. Franchisee dashboard graphs  · **M**
Payout-over-time, energy-delivered, settled-vs-pending, and per-charger breakdown on the franchisee
dashboard. Franchisee-scoped analytics endpoint + range picker.
- **Value:** franchisee self-service analytics; less support load.
- **Issues:** 2 (analytics endpoint → dashboard graphs — the remaining two from the franchisee-dashboard set).
- **Why here:** reuses the Phase 4a aggregation pattern; no reason to build two bucketing engines.

---

## Phase P — Paytm payment-provider evaluation _(runs across Phases 1–3; ◆ decision by early Sept)_

**Driver:** Razorpay silently downgrades instant refunds to normal speed via opaque fraud-shield
rules (confirmed by Razorpay, ticket #19564492) — hurting customer refund experience.

This is an **investigation, not a commitment.** It is risk-gated: we spend only as far as each gate passes.

- **Gate 1 — Refund reliability spike** (the make-or-break): measure our real Razorpay instant-refund
  success rate, then test Paytm under the same conditions. Paytm must **materially beat** that
  baseline to justify anything further. _Runs in the background from day one._
- **Gate 2 — Split settlement viability:** Paytm's Split Settlement product looks architecturally
  compatible with our franchisee-payout model, but three items need Paytm's team + compliance sign-off
  (programmatic onboarding API, TDS handling, MID/RBI enablement). _Commercial conversation — externally gated._
- **Gate 3 — Commodity flows** (QR / webhooks / orders): low-risk, only tested if Gate 1 passes.
- **◆ Go / No-Go decision + ADR:** synthesize gates → full-replace, dual-rail, or abort.

> **Honest read:** research shows Paytm is *no more transparent* than Razorpay on refunds in its
> public docs, so Gate 1 must be proven by measurement. If Paytm doesn't clearly beat Razorpay,
> the recommended path is **abort the migration** and pursue Razorpay escalation / Refund Credits
> instead. We find that out cheaply, before committing.

- **Issues:** 7 (Gate 1 → Gate 2a commercial → Gate 2b technical → Gate 3 → decision+ADR → [contingent] abstraction → [contingent] cutover).

### Contingent: Payment-provider abstraction + cutover  · **L / XL** · _only if ◆ = go_
If we proceed, we build a provider-agnostic seam (so Paytm slots in alongside Razorpay), then run
a phased cutover — the dominant cost being **re-onboarding every franchisee** onto Paytm's
settlement rail. Scoped as placeholders today; re-sliced into real work only after the decision.

---

## Dependencies & external risks

| Item | Risk | Mitigation |
|---|---|---|
| Paytm Gate 2 | Externally gated on Paytm's commercial/compliance team | Started day one, in parallel; not on the critical path for Phases 1–4 |
| Paytm Gate 1 | May show no improvement → migration unjustified | Cheap spike first; abort-friendly by design |
| Charger WS auth rollout | Fielded chargers need keys provisioned | Per-charger enforcement + global flag = no flag-day outage |
| OCPI Google feed | Google POI identity is permanent once published | Staging canary before prod (ADR 0015) |
| Phase 4 grouping | Franchisee graphs depend on the shared aggregation | Build admin Reports aggregation (4a) first, franchisee graphs (4b) reuse it |

## Sequencing principles

1. **Ship what's in flight** (OCPI) before opening new fronts — with quick wins riding along.
2. **Start externally-gated clocks early** (Paytm commercial talks) so they never block later.
3. **Security can jump the queue** — WS auth is pull-forward-able if exposure is judged urgent.
4. **Thin slices** — every initiative ships in independently-demoable increments; quick wins
   (remove Gross, `/my-charges`) land in Phase 1.
5. **Group shared work** — franchisee graphs sit with admin Reports to reuse one aggregation engine.
6. **Gate expensive bets** — Paytm spend stops at the first failed gate.

---

_All initiatives are fully specified (issues + acceptance criteria under `.scratch/<initiative>/`;
ADRs in `docs/adr/`). This roadmap sequences them; it does not re-plan them._
