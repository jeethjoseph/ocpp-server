# Confirm the aggregate reduction and re-baseline

Status: ready-for-agent

## What to build

With the frame duplicate and the health-check transactions gone, establish what the
account actually ingests now and record it as the new baseline — so future growth is
judged against a real figure rather than the stale pre-change one.

Pre-change baseline, for comparison:

| Usage metric | GB / 30 days |
|---|---|
| TracingBytes | 9.51 |
| LoggingBytes | 9.29 |
| MetricsBytes | 9.03 |
| ApmEventsBytes | 0.68 |
| BrowserEventsBytes | 0.54 |
| **Total** | **~29** (of a 100 GB free allowance) |

Close with the headroom question this whole exercise was for: does the diagnostic
bundle fan-out — currently off, and unmeasured because its entity has never been
created — plus expected fleet growth still fit inside the free allowance?

## Acceptance criteria

- [ ] Total monthly ingest re-measured over a **full week** post-change and extrapolated, broken down by usage metric.
- [ ] Before/after stated for each of Tracing, Logging and Metrics against the table above.
- [ ] New baseline and the headroom conclusion written into `docs/v1/llm-context-document.md` and `docs/v1/comprehensive-architecture-documentation.md`, per CLAUDE.md.
- [ ] If the reduction is materially smaller than expected, the remaining top contributors are identified and raised as follow-up tickets rather than left implicit.

## Blocked by

- `01-drop-library-frame-duplicate.md`
- `02-exclude-health-check-from-apm.md`
