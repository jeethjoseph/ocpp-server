# Stop instrumenting the health check as an APM transaction

Status: ready-for-agent

## What to build

The container liveness probe calls the health endpoint every ~15 seconds in each
environment. New Relic records every one of those calls as a full web transaction —
the handler, five framework middleware spans, plus the Postgres and Redis round-trips
the check legitimately performs.

At ~5,729 calls/day/environment (~11,458 total) it is the **single largest transaction
on the account**, ahead of real charging traffic, and the main driver of both Tracing
(~9.5 GB/month) and Metrics (~9.0 GB/month) ingest. Its entire information content is
"the process is up", which the probe itself already establishes.

Make the health endpoint invisible to APM **without changing what it does**. It must
still run its real database and Redis connectivity checks and return the same payload
and status codes — container healthchecks and any external monitor depend on that
behaviour, so this is a telemetry change only.

## Acceptance criteria

- [ ] The health-check transaction no longer appears in `Transaction` data in New Relic for either environment.
- [ ] The spans it generated — framework middleware, Postgres select, Redis ping attributable to the probe — stop being recorded.
- [ ] Endpoint behaviour is unchanged: same response body, same status codes, still genuinely exercises DB and Redis.
- [ ] Container healthchecks keep passing; no container is marked unhealthy after the change.
- [ ] **A real failure stays observable.** If DB or Redis is down the endpoint still reports it, and that failure still reaches the logs and Sentry even though APM ignores the transaction. Verify by forcing one dependency down.
- [ ] Measured in New Relic: total `Span` volume drops materially from the ~249,704/day baseline over a comparable window. Record before/after in the comments.

## Blocked by

None — can start immediately.
