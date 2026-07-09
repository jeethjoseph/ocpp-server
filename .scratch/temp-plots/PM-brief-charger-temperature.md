# Charger Temperature — What We Can See Today

_Prepared: 2 July 2026 · For: Project Manager · Context: staging data, chargers VOW0001 and V7C_Test, 1 July 2026_

## In one line

We can already track the **internal electronics temperature** of each charger over time, and we've charted it for the two chargers you asked about. What we *cannot* yet see is the **cable/plug temperature during a charging session** — the chargers don't currently send us that reading.

---

## What you asked for

A view of temperature across 1 July for two chargers (VOW0001 and V7C_Test), with the charging sessions marked so we can see start and end times, plus the high/low/average.

Three charts are attached (in this folder):

- **VOW0001 — full day** and a **zoomed 09:00–15:00 view** with each charging session colour-coded.
- **V7C_Test — full day**, with sessions marked.

All times are shown in **IST**.

## What the charts show

- **VOW0001** ran **6 charging sessions** between roughly 09:15 and 14:20. Temperature climbs while charging (peaking around **52 °C**) and cools back toward **~28 °C** when idle between sessions. Average across the busy window was **~41 °C**.
- **V7C_Test** ran **2 sessions** in the afternoon (about 14:20–17:00). It sat warm (~42–45 °C) throughout, peaking at **45.8 °C**, then cooled to ~30 °C once charging stopped. Average **~41 °C**.

The pattern is intuitive: the harder and longer a charger works, the hotter its electronics get; it cools down when idle. This is useful fleet-health information — a charger running hot while *idle* on a summer afternoon would be an early warning sign.

---

## The important nuance: two different "temperatures"

There are two temperatures people usually mean, and they are **not the same thing**:

| Temperature | What it is | Do we record it? |
|---|---|---|
| **Charger electronics temperature** | Heat inside the charger's internal comms hardware. Reported continuously, even when idle. | ✅ **Yes** — this is what the charts show |
| **Cable / plug / vehicle temperature** | Heat in the charging cable or connector *during* a session (a safety-relevant reading). | ❌ **No** — the chargers don't send this today, so we store nothing |

So when we say "charger temperature," today we mean the **electronics** temperature. If the business needs the **cable/connector** temperature (e.g. for safety monitoring), that's a **separate piece of work**: we'd first need to confirm the charger hardware even reports it, and then build the capture for it. It's **not currently on the plan** — worth a decision if it matters.

---

## What's already in the product

Staff can already see this on each charger's detail page: a **live "Modem Temperature" chart** showing the last 24 hours. It's a real-time health tile — good for "how is this charger right now," but it can't do historical ranges, min/avg/max summaries, or exports. (The charts I produced for you were generated manually from the database to cover a specific past day.)

## What's already planned (and where this fits the roadmap)

Good news — the richer version of exactly this is **already scheduled**:

> **Phase 4 — Admin Reports tab (Temperature first), targeted late August.**

That work delivers a proper **Reports** section for admins:
- Pick any charger and any date range (up to 90 days)
- See temperature as an **average line with a high–low band**
- **Download a CSV** for offline analysis

In short: the manual charts I made this week become a **self-service report** any admin can pull, without engineering help. No new roadmap item is needed for the electronics-temperature reporting — it's covered by Phase 4a.

---

## Decisions / what we'd like from you

1. **Session markers on the reports.** The planned Reports view shows temperature trends but does **not** overlay charging-session start/end markers (the coloured bands in the VOW0001 chart). If that overlay is valuable to you, we can add it — small extra scope. **Do you want it?**
2. **Cable/connector temperature.** If safety-oriented cable temperature matters to the business, flag it — it's genuinely new work (not a tweak) and isn't on the roadmap today.
3. **Timing.** The self-service temperature report lands in **late August** as currently sequenced (it sits behind the in-flight Google Maps feed, the security hardening, and the payments work). If you need it sooner, we can discuss re-prioritising.

_Attachments: `temperature_VOW0001_V7C_Test_2026-07-01_IST.png`, `temperature_VOW0001_2026-07-01_0900-1500_IST.png`, `temperature_V7C_Test_2026-07-01_IST.png` (this folder)._
