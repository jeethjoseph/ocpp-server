# Charger Utilisation Report — trailing 30 days

**Generated:** 2026-07-29 (13:44 IST) · **Window:** 2026-06-29 00:00 IST → 2026-07-29 13:44 IST (30.57 days) · **Source:** staging + prod RDS, read-only

## Definitions (as agreed)

- **Utilisation** = plugged-in wall-clock hours (`start_time` → `end_time`), i.e. connector occupancy. Includes suspended time — a latched session sitting in its 12 h suspend window counts as occupied.
- **Charger type** = `connector.connector_type`. Every charger in both fleets has exactly one connector, so no mixed-type ambiguity exists in practice.
- **Solar band (KSEB)** = 09:00–16:00 IST (7 h/day ceiling). **Non-solar** = the remaining 17 h. Sessions crossing a boundary are apportioned by exact overlap, per day.
- **Included sessions**: COMPLETED, STOPPED, BILLING_FAILED, plus live (STARTED/RUNNING/SUSPENDED/PENDING_STOP) clipped at report time; sessions spanning the window edges are clipped to the window. Excluded: CANCELLED / FAILED / PENDING_START. *In this window the exclusion was moot — every overlapping row was COMPLETED, STOPPED, or RUNNING in both envs.*
- **Average** = total hours of the (type × band) ÷ count of chargers of that type — including chargers with zero sessions — shown as a 30-day total and ÷30.57 per-day, with % against each band's own ceiling.

## Production

| Type | Chargers | Sessions | Total h | Solar h | Non-solar h | Per charger / 30d | **Per charger / day** | Solar h/day (% of 7h) | Non-solar h/day (% of 17h) |
|---|---|---|---|---|---|---|---|---|---|
| Socket | 4 | 129 | 127.2 | 64.3 | 62.9 | 31.8 h | **1.04 h (4.3%)** | 0.53 (7.5%) | 0.51 (3.0%) |
| Type2 | 4 | 57 | 45.2 | 9.4 | 35.8 | 11.3 h | **0.37 h (1.5%)** | 0.08 (1.1%) | 0.29 (1.7%) |

Per-charger detail (prod):

| Charger | Type | Created | Sessions | Total h | Solar h |
|---|---|---|---|---|---|
| VOW0001 | Type2 | 2026-03-16 | 0 | 0 | 0 |
| VOW0002 | Socket | 2026-03-25 | 0 | 0 | 0 |
| VOW0003 | Socket | 2026-03-27 | 0 | 0 | 0 |
| VOW0006 | Type2 | 2026-05-28 | 12 | 20.4 | 1.4 |
| VOW0007 | Socket | 2026-05-28 | 94 | 124.1 | 62.5 |
| VOW0008 | Type2 | 2026-06-02 | 21 | 16.3 | 7.1 |
| VOW0009 | Type2 | 2026-06-02 | 24 | 8.6 | 0.9 |
| VOW0010 | Socket | 2026-07-03 | 35 | 3.1 | 1.8 |

Observations:
- **Prod Socket usage is solar-heavy** (0.53 h/day at 7.5% of the solar ceiling vs 3.0% of non-solar) — daytime charging dominates. Prod Type2 is the opposite: 79% of its hours fall outside solar hours (mostly VOW0006/VOW0009 overnight/evening sessions).
- **Three prod chargers (VOW0001/0002/0003) had zero sessions all month.** They drag the averages down; with them removed, active-charger utilisation is Socket 2.08 h/day, Type2 0.49 h/day.
- **VOW0007 alone is 74% of all prod utilisation hours.**
- VOW0010 was commissioned 2026-07-03 (inside the window). Pro-rating its available days moves Socket to 1.08 h/day (vs 1.04) — negligible.

## Staging

| Type | Chargers | Sessions | Total h | Solar h | Non-solar h | Per charger / 30d | **Per charger / day** | Solar h/day (% of 7h) | Non-solar h/day (% of 17h) |
|---|---|---|---|---|---|---|---|---|---|
| Socket | 3 | 349 | 668.2 | 199.2 | 469.0 | 222.7 h | **7.29 h (30.4%)** | 2.17 (31.0%) | 5.11 (30.1%) |
| Type2 | 1 | 53 | 27.2 | 21.6 | 5.6 | 27.2 h | **0.89 h (3.7%)** | 0.71 (10.1%) | 0.18 (1.1%) |

Per-charger detail (staging, non-test):

| Charger | Type | Sessions | Total h | Solar h |
|---|---|---|---|---|
| VOW0001 | Type2 | 53 | 27.2 | 21.6 |
| VOW0002 | Socket | 94 | 194.7 | 58.1 |
| VOW0004 | Socket | 126 | 224.8 | 55.2 |
| VOW0005 | Socket | 129 | 248.7 | 85.9 |

Staging "utilisation" here is mostly synthetic/dev traffic (~7.3 h/day/socket, spread evenly across bands — consistent with automated testing, not human charging patterns). Treat it as a data-volume sanity check, not utilisation.

## Test-charger exclusions (veto if wrong)

Filtered by name pattern (`*Test*`, `Simulator` vendor, `Staging_*`, `Chargemode_*`):

| Env | Charger | Why excluded | Sessions dropped | Hours dropped |
|---|---|---|---|---|
| staging | V3C_Test | name | 232 | 7.5 |
| staging | V7C_Test | name | 72 | 8.1 |
| staging | V3C_Test1 | name | 0 | 0 |
| staging | V7C_Test2 | Simulator vendor | 0 | 0 |
| staging | Chargemode_1 | vendor-eval unit | 0 | 0 |
| prod | V3C_Test | name | 0 | 0 |
| prod | V7C_Test | name | 8 | 7.8 |
| prod | Chargemode_1 | vendor-eval unit | 0 | 0 |
| prod | Staging_VOW0002 | staging unit in prod DB | 0 | 0 |
| prod | Staging_VOW0004 | staging unit in prod DB | 0 | 0 |

⚠️ Prod's DB contains 5 test/staging-named chargers. If `Chargemode_1` or `V7C_Test` (prod, 8 real-looking sessions) are actually customer hardware, say so and I'll fold them back in.

## Caveats

1. Wall-clock occupancy **includes suspended time**. With the new 12 h latched suspend window (commit `81e2628`), one latched car left plugged in overnight adds up to 12 idle-but-occupied hours. If you want energy-delivering hours instead, that needs a `meter_value`-based query (heavier; not run).
2. Averages include zero-session chargers by design (a dead charger is 0% utilised, not excluded).
3. All timestamps converted to IST for banding; DB values are UTC.

## Max utilisation (peak days, same window & definitions)

Per-charger per-IST-day plugged-in hours; test chargers excluded. SQL: [`util_daily.sql`](./util_daily.sql).

### Production

| Metric | Value |
|---|---|
| Max charger-day, any type | **VOW0007 (Socket): 11.16 h on 2026-07-26** (5.12 h solar) |
| Max Type2 charger-day | VOW0008: 4.84 h on 2026-07-18 (2.91 h solar) |
| Max solar-band charger-day | VOW0007: 5.12 h of the 7 h band on 2026-07-26 (73% of band) |
| Peak fleet day, Socket | 2026-07-26: 11.16 h (all on VOW0007) |
| Peak fleet day, Type2 | 2026-07-18: 8.31 h across chargers (4.90 h solar) |

Per-charger maxima (prod): VOW0006 3.33 h · VOW0007 11.16 h · VOW0008 4.84 h · VOW0009 3.25 h · VOW0010 0.92 h. Active days out of ~31: VOW0007 26, VOW0008 13, VOW0009 11, VOW0006 10, VOW0010 8.

All top-5 prod charger-days are VOW0007, and all fall in the last 2 weeks of the window — usage is trending up. Its ceiling (11.16 h/day, 46% of 24 h) shows what a well-placed socket charger can do; the fleet average (1.04 h) is dragged by placement, not demand ceiling.

### Staging

| Metric | Value |
|---|---|
| Max charger-day | VOW0004 (Socket): 16.44 h on 2026-07-07 |
| Max solar-band charger-day | VOW0005: 6.38 h of 7 h band on 2026-07-16 (91%) |
| Peak fleet day, Socket | 2026-07-09: 34.97 h across 3 chargers (avg 11.7 h/charger) |
| Peak fleet day, Type2 | 2026-07-01: 4.09 h (VOW0001, fully solar) |

Staging sockets were active 30–31 days out of 31 — again consistent with automated traffic.

## Reproduction

SQL: [`util.sql`](./util.sql) (averages) and [`util_daily.sql`](./util_daily.sql) (per-day peaks) — run read-only against either env via the standard SSM → postgres-container `psql` pattern. Aggregation math: total ÷ charger-count ÷ 30.57.
