# Drop the superseded header columns after a soak period

Status: ready-for-agent

## What to build

The contract half of the expand/contract in issue 05. Issue 05 stops writing `epoch`, `bundle_seq`, `boot`, `first_record`, `last_record`, `overflow_delta`, `gap_records` and `header_valid` and makes them nullable; this issue removes them.

Deliberately separate and deliberately later. Dropping in the same migration would destroy the historical values with no way back if the replacement underperforms in the field — and this feature has already been wrong once about what it could rely on. The columns cost nothing to keep for a release.

**Entry condition — do not start until all of these hold:**

1. Issue 05 has been live on staging for at least one full upload cycle across a reboot.
2. `first_utc` / `last_utc` are populating for real traffic, including at least one multi-boot bundle and one unanchored bundle.
3. The UTC window has been observed producing a plausible loss signal on real traffic — not merely populating, but agreeing with something independently known (a reboot, a known outage, a wrap event).

Generate the migration with Aerich. **Never hand-edit a past migration to remove these columns** — the `aerich.content` snapshot stays poisoned and every future `aerich migrate` re-emits the cleanup as an unrelated ALTER.

## Acceptance criteria

- [ ] All three entry conditions verified and recorded in this issue's Comments before any code is written.
- [ ] Aerich-generated migration drops the superseded columns.
- [ ] `aerich upgrade` then `aerich downgrade` run clean locally.
- [ ] No code references the dropped columns outside migrations and ADRs.
- [ ] `docker exec ocpp-backend pytest tests/test_diagnostics_endpoint.py tests/test_diagnostic_bundle_service.py tests/test_diagnostic_fanout.py tests/test_diagnostic_redaction.py tests/test_charger_auth_service.py` passes (baseline: 63 passed across the five diagnostics files).

## Blocked by

- Issue 05, plus the soak period and the scope decision above
