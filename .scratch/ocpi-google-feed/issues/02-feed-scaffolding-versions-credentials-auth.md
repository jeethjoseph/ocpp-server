# Feed scaffolding: Versions + Credentials + token auth + `OCPI_ENABLED` env wiring

Status: ready-for-agent

## What to build

Stand up the OCPI CPO router skeleton under `/ocpi/cpo/2.2/` with the two handshake modules and OCPI token auth, gated by `OCPI_ENABLED`. This is the entry path Google hits before pulling Locations; Locations content lands in issue 03.

**Endpoints:**
- **Versions** — `GET /ocpi/versions` returns the supported version(s) with a URL to the 2.2.1 version details; `GET /ocpi/cpo/2.2/` (version details) lists the endpoints we serve (`credentials`, `locations`).
- **Credentials** — `GET/POST/PUT/DELETE` per OCPI 2.2.1 token-exchange handshake (server role). Implement the token registration flow well enough for a consumer to complete the handshake.

**Auth:**
- OCPI **`Authorization: Token <base64>`** dependency — **not Clerk**. Validate against a configured consumer token. Reject with the OCPI status-code envelope (not bare HTTP) on bad/missing token.
- All `/ocpi/*` routes bypass Clerk middleware.

**Config / gating:**
- `OCPI_ENABLED` (default `false`) — when false, the router returns 404/disabled.
- `OCPI_PARTY_ID` (`VLT` prod / `VLS` staging), `OCPI_COUNTRY_CODE=IN`.
- Wire all new env vars through the full checklist: `.env.example`, `.env.staging.example`, `.env.prod.example`, **and** `backend.environment:` in all three compose files, plus a startup log warning if `OCPI_ENABLED=true` but token/party unset.

See [ADR 0015](../../../docs/adr/0015-ocpi-identity-scheme.md) and the env-var checklist in CLAUDE.md.

## Acceptance criteria

- [ ] `GET /ocpi/versions` and the 2.2.1 version-details endpoint return spec-shaped OCPI response envelopes (`status_code`, `status_message`, `timestamp`, `data`).
- [ ] Credentials handshake (token exchange) completes for a registering consumer; tokens validated on subsequent requests.
- [ ] Requests without a valid OCPI token are rejected with the OCPI error envelope; Clerk is not involved on any `/ocpi/*` route.
- [ ] With `OCPI_ENABLED=false` the feed is disabled (404/disabled), verified by test.
- [ ] `OCPI_ENABLED` / `OCPI_PARTY_ID` / `OCPI_COUNTRY_CODE` present in all three `.env.*.example` files and in `backend.environment:` of all three compose files; startup logs a loud warning on enabled-but-misconfigured.
- [ ] `docker exec ocpp-backend env | grep OCPI` shows the vars inside the container.
- [ ] Tests cover versions, credentials handshake, auth accept/reject, and the disabled gate.

## Blocked by

None — independent of the schema migration; can run in parallel with issue 01.
