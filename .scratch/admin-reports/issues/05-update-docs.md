# 05 — Update architecture + LLM-context docs for Reports

Status: ready-for-agent

## What to build

Update the project's living documentation to reflect the new admin Reports feature and its aggregation pattern, per the CLAUDE.md instruction to keep these current after changes.

- `docs/v1/llm-context-document.md` — add the Reports surface, the temperature aggregation endpoints, and the subreport framework to the context doc.
- `docs/v1/comprehensive-architecture-documentation.md` — document the reporting layer, the raw-SQL `date_trunc` bucketing pattern, the 90-day retention cap, and how future subreports (Energy, Signal, Sessions/revenue) slot into the framework.

Reference the ADR from slice 01 rather than duplicating its rationale.

## Acceptance criteria

- [ ] `llm-context-document.md` describes the Reports surface and temperature endpoints
- [ ] `comprehensive-architecture-documentation.md` documents the aggregation pattern, 90-day cap, and subreport framework
- [ ] Docs link to the Reports ADR rather than restating it
- [ ] No stale references — reflects the endpoints and UI as actually shipped in slices 02–04

## Blocked by

- 02 — Temperature aggregation endpoint (hourly/daily min-avg-max buckets)
- 03 — Reports tab shell + Temperature subreport chart
- 04 — Temperature report CSV export
