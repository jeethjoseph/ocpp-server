# API contract cleanup: drop `budget_remaining`, expose stale threshold, share VPA regex

Status: ready-for-agent

## Parent

`.scratch/active-session-on-my-charges/PRD.md`

## What to build

Three small contract changes on `/api/public/qr-active-sessions` and adjacent surfaces.

1. **Drop `budget_remaining` from the response.** It is numerically identical to `refund_if_stopped_now`; exposing both invites API consumers to assume there's a difference and to derive one. Single field, single meaning.
2. **Add `stale_threshold_seconds` to each `waiting`-state entry.** The value is `QR_PAYMENT_PENDING_TIMEOUT` (env-configurable, default 300). The frontend uses this to render specific copy ("auto-refund in 4 minutes") instead of vague hardcoded "in a few minutes." Compute it as `max(0, threshold - age_seconds)` per-row so it's the remaining time, not the absolute threshold.
3. **Single source for `VPA_PATTERN`.** Today it lives independently in `public_qr_transactions.py` and `public_qr_active_sessions.py`. Move it to a shared backend module (e.g. `core/validators.py` or `routers/_shared.py`) and import from both call sites. The frontend mirror (`VPA_INPUT_PATTERN` in `app/my-charges/page.tsx`) cannot share the runtime value; add a comment on both sides referencing the other with "MUST stay in sync."

## Acceptance criteria

- [ ] Response no longer contains `budget_remaining`; tests updated to assert absence.
- [ ] `waiting` entries include `stale_threshold_seconds` as a non-negative integer (remaining time before auto-refund).
- [ ] Both `public_qr_transactions.py` and `public_qr_active_sessions.py` import `VPA_PATTERN` from a single module; no duplicate regex literal.
- [ ] Existing pytest suite green after the field rename.

## Blocked by

None — can start immediately.
