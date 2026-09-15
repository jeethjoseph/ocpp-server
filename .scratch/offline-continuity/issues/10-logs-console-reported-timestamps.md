# Surface charger-reported timestamps on the Logs Console

Status: ready-for-agent

## What to build

Show, on the **Logs Console** and its CSV export, the timestamp the charger put on the frame — alongside the receipt time already displayed.

The reported timestamp is already retained: every inbound frame is written verbatim into the log row's payload and kept for the retention window. Nothing is lost. But it lives inside JSON, so it cannot be read at a glance or exported.

Meanwhile the log row's own `timestamp` column is a server-receipt value despite the name. On a table of OCPP messages, the column called *timestamp* is the one clock that is not the OCPP timestamp — the same class of trap as the documented `message_type` collision. It is the sort key, the date filter, the pagination cursor, the retention key, and the CSV's `timestamp_ist` column.

This matters under [[offline-charging-continuity]]: a replayed queue lands as hundreds of rows at one receipt instant, so an export implies the charger sent hundreds of frames in one second — the triage surface degrading in exactly the scenario that makes someone open it.

**Extract at render, do not add a column.** The log table takes every frame from the whole fleet; an index on it is not free, and nobody filters this console by charger-reported time — they filter by "around 3pm", which is genuinely receipt. Extraction is bounded by the existing page size (ADR 0014's bounded query surface).

Per the timestamp conventions in CLAUDE.md, the export column is IST and named so the zone is unambiguous — and here the name must also disambiguate *which clock*.

## Acceptance criteria

- [ ] Rows show the charger-reported timestamp beside the receipt timestamp, blank where the frame carried none
- [ ] The CSV export gains a reported column in IST, named so it is not confusable with the receipt column
- [ ] No schema change and no new index
- [ ] Frames with an absent or unparseable timestamp render blank rather than erroring
- [ ] The existing filter, sort and keyset pagination continue to operate on receipt time, unchanged
- [ ] A test asserts the IST offset on the new export column
- [ ] The naming trap is documented so nobody writes a query assuming the log timestamp is the charger's

## Blocked by

None - can start immediately
