# Fail loudly on missing or mismatched supplier identity

Status: done

## What to build

Make it impossible to boot the backend with a supplier identity that has not been deliberately configured. The GSTIN defect went undetected across 1,200 invoices and four months because both halves of the supplier identity have silent fallbacks: the business name is a hardcoded string default in the invoice service, and the GSTIN defaults to an empty string. Nothing ever asserted they belonged together, and nothing complained when one was wrong.

Three guards:

1. **Remove the hardcoded name default.** `VOLTLYNC_BUSINESS_NAME` must come from configuration. No literal company name in application code — a legal entity name is not a sensible default.
2. **Refuse to start when the supplier identity is incomplete.** `VOLTLYNC_GSTIN` and `VOLTLYNC_BUSINESS_NAME` must both be present and non-empty. Follow the existing startup-validation pattern in `main.py` used for other critical variables.
3. **Assert the GSTIN is internally consistent and matches the expected entity type.** A GSTIN encodes a state code, a PAN, and a checksum. Validate the format (`^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]{3}$`), that the leading state code matches `VOLTLYNC_STATE_CODE`, and that the PAN's fourth character matches a new `VOLTLYNC_ENTITY_TYPE` variable (`C` company, `F` firm/LLP, `P` individual). Had this check existed, it would have caught the defect on the first deploy — the configured GSTIN carries `F` while the configured name says "PRIVATE LIMITED".

Per the env-var checklist in CLAUDE.md, `VOLTLYNC_ENTITY_TYPE` must be added to `.env.example`, `.env.staging.example`, `.env.prod.example` **and** the `backend.environment:` block of all three compose files, or the container will not see it.

Guard 3 must be a hard failure, not a warning. A warning is what the current empty-string default effectively is.

## Acceptance criteria

- [ ] `VOLTLYNC_BUSINESS_NAME` has no in-code default; the literal company name appears nowhere in application source
- [ ] Startup aborts with a clear, actionable message when `VOLTLYNC_GSTIN` or `VOLTLYNC_BUSINESS_NAME` is unset or empty
- [ ] Startup aborts when the GSTIN fails format validation, when its state code disagrees with `VOLTLYNC_STATE_CODE`, or when the PAN entity-type character disagrees with `VOLTLYNC_ENTITY_TYPE`
- [ ] `VOLTLYNC_ENTITY_TYPE` added to all three `.env*.example` files and to `backend.environment:` in all three compose files
- [ ] Tests cover each failure mode, including the real historical case: name says company, GSTIN PAN says firm → refuse to start
- [ ] `docker compose build backend && docker exec ocpp-backend env | grep VOLTLYNC_ENTITY_TYPE` confirms the variable reaches the container
- [ ] Affected per-file pytest green (`docker exec ocpp-backend pytest`)

## Blocked by

- Ordering note: deploy **after** issue 03's data correction, so the corrected configuration and the historical rows agree before validation is enforced.
