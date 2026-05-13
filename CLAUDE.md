
## How I Work
- Always create a plan before coding
- Ask me before making architectural changes
- When migrations are necessary I prefer to do it with Aerich. Only create migrations necessary after you verify that it is impossible to generate it with Aerich.
- Keep functions under 40 lines
- Commit-ready code only — no TODOs in final output
- At the start of every session refer to /Users/raalshasan/makaratech/idofthings/ocpp-server/docs/v1/llm-context-document.md
- For larger context and architecture related context refer to this /Users/raalshasan/makaratech/idofthings/ocpp-server/docs/v1/comprehensive-architecture-documentation.md
- When you are done with making changes, update these documents - Users/raalshasan/makaratech/idofthings/ocpp-server/docs/v1/llm-context-document.md, /Users/raalshasan/makaratech/idofthings/ocpp-server/docs/v1/comprehensive-architecture-documentation.md

## Build verification (before declaring done)
- **Frontend**: after any `frontend/` edit, run `cd frontend && npm run build` locally. `next lint` and `tsc --noEmit` are NOT sufficient — the production build enforces `@typescript-eslint/no-unused-vars`, `react/no-unescaped-entities`, and other rules the scoped lint misses.
- **Backend**: run `docker exec ocpp-backend pytest` for the affected test files.
- **Docker build parity**: when changes touch the build (new imports, new deps, config), run `docker compose build frontend` / `docker compose build backend` locally to catch image-level failures before they hit staging.
- Never declare a change "done" based only on `tsc` output or partial lint runs — staging/prod rebuilds enforce the full ruleset.

## Environments
- **Production**: `app.voltlync.com` — branch `deploy`, `docker-compose.prod.yml` + `.env.prod`, `make prod-*` targets
- **Staging**: `staging.voltlync.com` — branch `develop`, `docker-compose.staging.yml` + `.env.staging`, `make staging-*` targets
- Both share the same Clerk app and Razorpay **live** keys (QR payments require live mode)
- Razorpay webhook handlers gracefully skip "not found" transactions (cross-environment events) — do not change this to raise errors

## Env vars (CRITICAL — read before adding any new env var)

**Adding a new env var to `.env.example` / `.env.staging.example` / `.env.prod.example` is NOT enough.** Docker compose's `--env-file` flag only loads vars into the *shell where compose runs* (for `${VAR}` substitution in YAML). It does **not** automatically pass them into the container.

For a new env var to reach the Python app inside the container, you must add it to the `environment:` block of the **backend** service in all three compose files:
- `docker-compose.yml` (dev)
- `docker-compose.staging.yml`
- `docker-compose.prod.yml`

Pattern: `- NEW_VAR=${NEW_VAR:-sensible_default}` so missing values fall through to a default rather than empty-string.

Symptom of forgetting: file on disk has the value, `os.getenv("NEW_VAR")` inside the container returns empty / None, `docker exec <container> env | grep NEW_VAR` shows nothing. This wasted half an hour during the GST deploy.

Checklist when adding a new env var:
1. `.env.example` — add with comment + default
2. `.env.staging.example` and `.env.prod.example` — add with the appropriate value for that env
3. `docker-compose.yml` — add to `backend.environment:`
4. `docker-compose.staging.yml` — add to `backend.environment:`
5. `docker-compose.prod.yml` — add to `backend.environment:`
6. `backend/main.py` startup event — log a warning/error if the var is critical and empty (so a misconfigured deploy fails loud)
7. Run `docker compose build backend && docker exec <container> env | grep NEW_VAR` to verify locally before claiming done